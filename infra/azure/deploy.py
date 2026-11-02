"""Deploy the portfolio API and zero-idle worker using an existing Azure CLI login.

Secrets are read from a gitignored env file and sent directly to ARM over HTTPS.
The subscription must retain its spending limit. No registry or logging service
with an ongoing base charge is created. See README.md in this directory.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--subscription", required=True)
    p.add_argument(
        "--image", required=True, help="public GHCR image pinned to a commit/digest"
    )
    p.add_argument("--env-file", default=".deployment/runtime.env")
    p.add_argument(
        "--git-sha",
        help="source commit for a digest-pinned image (commit tags infer it)",
    )
    p.add_argument("--secrets-file", default=".deployment/secrets.json")
    p.add_argument("--resource-group", default="strata")
    p.add_argument("--environment", default="strata-production")
    p.add_argument("--location", default="westus2")
    p.add_argument(
        "--az-python", help="Python interpreter containing azure.cli (uv on Windows)"
    )
    p.add_argument("--only", choices=["api", "worker"])
    a = p.parse_args()
    az = [a.az_python, "-m", "azure.cli"] if a.az_python else ["az"]
    token = json.loads(
        subprocess.check_output(
            az
            + [
                "account",
                "get-access-token",
                "--subscription",
                a.subscription,
                "--resource",
                "https://management.azure.com/",
                "-o",
                "json",
            ]
        )
    )["accessToken"]

    def arm(
        method: str, path: str, body: dict | None = None, version="2024-03-01"
    ) -> dict:
        req = urllib.request.Request(
            f"https://management.azure.com{path}?api-version={version}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # ARM validation errors do not contain secret values, but do not dump
            # full requests or configurations, even on failure.
            error = json.load(exc).get("error", {})
            raise RuntimeError(
                f"ARM {exc.code}: {error.get('code')}: {error.get('message')}"
            ) from None

    sub = arm("GET", f"/subscriptions/{a.subscription}", version="2022-12-01")
    if sub.get("subscriptionPolicies", {}).get("spendingLimit") != "On":
        raise SystemExit("Refusing deployment: subscription spending limit is not On")
    root = f"/subscriptions/{a.subscription}/resourceGroups/{a.resource_group}/providers/Microsoft.App"
    environment_id = f"{root}/managedEnvironments/{a.environment}"
    environment = arm("GET", environment_id, version="2026-07-01")
    if environment["properties"].get("environmentMode") != "WorkloadProfiles":
        raise SystemExit(
            "Use a WorkloadProfiles environment; Express cannot run jobs or custom domains"
        )
    values = dict(
        line.split("=", 1)
        for line in Path(a.env_file).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )
    source_sha = a.git_sha or a.image.rsplit(":", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise SystemExit(
            "Use a full commit image tag, or provide --git-sha for report provenance"
        )
    values["STRATA_GIT_SHA"] = source_sha
    secret_values = json.loads(Path(a.secrets_file).read_text())
    refs = {"DATABASE_URL": "database-url", "STRATA_DATA_KEY": "data-key"}
    secrets = [{"name": refs[k], "value": values[k]} for k in refs]
    env = [
        {"name": k, **({"secretRef": refs[k]} if k in refs else {"value": v})}
        for k, v in values.items()
    ]

    container = {
        "name": "api",
        "image": a.image,
        "env": env,
        "command": ["python", "-m", "uvicorn"],
        "args": [
            "strata.api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--no-access-log",
            "--no-proxy-headers",
        ],
        "resources": {"cpu": 1, "memory": "2Gi"},
        "probes": [
            {
                "type": "Startup",
                "tcpSocket": {"port": 8000},
                "periodSeconds": 5,
                "failureThreshold": 60,
            },
            {
                "type": "Readiness",
                "tcpSocket": {"port": 8000},
                "periodSeconds": 10,
                "failureThreshold": 3,
            },
        ],
    }
    api = {
        "location": a.location,
        "tags": {"project": "strata"},
        "properties": {
            "managedEnvironmentId": environment_id,
            "workloadProfileName": "Consumption",
            "configuration": {
                "activeRevisionsMode": "Single",
                "secrets": secrets,
                "ingress": {
                    "external": True,
                    "targetPort": 8000,
                    "transport": "auto",
                    "allowInsecure": False,
                },
            },
            "template": {
                "containers": [container],
                "scale": {
                    "minReplicas": 0,
                    "maxReplicas": 1,
                    "rules": [
                        {
                            "name": "http",
                            "http": {"metadata": {"concurrentRequests": "10"}},
                        }
                    ],
                },
            },
        },
    }
    query = (
        "SELECT count(*) FROM public.jobs WHERE "
        "(status='queued' AND run_after <= now()) OR "
        "(status='running' AND heartbeat_at < now() - interval '120 seconds')"
    )
    worker = {
        "location": a.location,
        "tags": {"project": "strata"},
        "properties": {
            "environmentId": environment_id,
            "workloadProfileName": "Consumption",
            "configuration": {
                "triggerType": "Event",
                "replicaTimeout": 2100,
                "replicaRetryLimit": 1,
                "secrets": secrets
                + [
                    {
                        "name": "scaler-connection",
                        "value": secret_values["scaler_connection"],
                    }
                ],
                "eventTriggerConfig": {
                    "parallelism": 1,
                    "replicaCompletionCount": 1,
                    "scale": {
                        "minExecutions": 0,
                        "maxExecutions": 1,
                        "pollingInterval": 30,
                        "rules": [
                            {
                                "name": "pending-jobs",
                                "type": "postgresql",
                                "metadata": {"query": query, "targetQueryValue": "1"},
                                "auth": [
                                    {
                                        "secretRef": "scaler-connection",
                                        "triggerParameter": "connection",
                                    }
                                ],
                            }
                        ],
                    },
                },
            },
            "template": {
                "containers": [
                    {
                        "name": "worker",
                        "image": a.image,
                        "env": env,
                        "command": ["python", "-m", "strata.jobs.worker"],
                        "args": ["--once", "--max-jobs", "1"],
                        "resources": {"cpu": 2, "memory": "4Gi"},
                    }
                ]
            },
        },
    }
    for kind, name, body in [
        ("api", "containerApps/strata-api", api),
        ("worker", "jobs/strata-worker", worker),
    ]:
        if a.only and a.only != kind:
            continue
        path = f"{root}/{name}"
        # Preserve certificate/domain bindings on later image updates.
        if kind == "api":
            try:
                existing = arm("GET", path)
                domains = (
                    existing["properties"]["configuration"]
                    .get("ingress", {})
                    .get("customDomains")
                )
                if domains:
                    body["properties"]["configuration"]["ingress"]["customDomains"] = (
                        domains
                    )
            except RuntimeError as exc:
                if "ARM 404" not in str(exc):
                    raise
        result = arm("PUT", path, body)
        for _ in range(100):
            state = result["properties"].get("provisioningState", "")
            if state in {"Succeeded", "Failed", "Canceled"}:
                break
            time.sleep(10)
            result = arm("GET", path)
        print(f"{kind}: {state}", flush=True)
        if state != "Succeeded":
            raise SystemExit(f"{kind} did not provision successfully")
        if kind == "api":
            print(
                "API hostname:",
                result["properties"]["configuration"]["ingress"]["fqdn"],
                flush=True,
            )


if __name__ == "__main__":
    main()
