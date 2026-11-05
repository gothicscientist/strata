# stratalab.cc portfolio deployment

The static Next.js export is on Cloudflare Pages (`strata-web`, assigned hostname
`strata-web-6ur.pages.dev`). The API and bounded queue workers use Azure Container
Apps in `westus2`, resource group `strata`, environment `strata-production`.
Supabase project `ghxzwjdjtepcwycgwknd` holds Postgres, private application data,
retention scheduling, and email authentication. Resend supplies SMTP.

The API's managed HTTPS address is
`https://strata-api.delightfulflower-446608ec.westus2.azurecontainerapps.io`.
`api.stratalab.cc` also has a managed Azure certificate. The frontend uses the
managed address so fresh domain DNS caches do not delay API access.

## Cost controls

- Azure for Students subscription spending limit must remain **On**. The deployment
  script refuses to proceed otherwise. Do not upgrade the subscription or remove
  its protection. The claimed student credit expires November 1, 2027.
- API: Consumption profile, 1 CPU / 2 GiB, minimum 0 and maximum 1 replica.
- Worker: Consumption event job, 2 CPUs / 4 GiB, minimum 0 and maximum 1 execution,
  one queue job per execution. The scaler polls every 30 seconds with a database
  role that can only read queue status/timing columns. It also detects stale jobs
  so a terminated execution can recover without another submission.
- No dedicated compute, paid container registry, or Log Analytics workspace is
  created. Runtime images are public GHCR packages built from this public repo.
- Cloudflare, Supabase, and Resend use their free plans. Quotas and account
  suspension/pausing can interrupt service; they are not permission to add a card
  or upgrade a plan. The Azure credit is a finite allowance, not permanent hosting.

An idle backend scales to zero. A new analysis normally waits for the queue poll
and a container start before computation begins; live checks took roughly 45–65
seconds per small job. Workspaces and encrypted data persist in Postgres.

## Runtime and secrets

`services/worker/Dockerfile` builds Python, R, pinned ADMIXTOOLS 2, methods docs,
worked examples, the reference library/PCA model, and the verified f2 release.
The final image checks that R still works after cleanup, under the runtime user.
The API overrides its default worker entrypoint to run Uvicorn. Reference downloads
are performed at build time, not when a visitor opens the app.

The local `.deployment/` directory and `apps/web/.env.local` are gitignored.
`.deployment/runtime.env` contains the runtime database connection and encryption
key. `.deployment/secrets.json` also contains the separate scaler connection and
role passwords. Back up these files privately, especially the data encryption key:
restoring the database alone cannot decrypt datasets without it. Never paste
their contents into a ticket, commit, browser frontend, or deployment log.

Database roles are `strata_runtime` (API/worker application access, not superuser
and not BYPASSRLS) and `strata_scaler` (queue count only). The browser receives only
the Supabase publishable key. Client RLS and API owner checks protect user data;
dataset keys cannot be read by browser roles.

No shared LLM key is installed. The assistant accepts an OpenAI or Anthropic key
for each request, creates a request-local provider, and closes it after streaming.
The key stays in page memory, is excluded from persisted messages and schemas,
and clears on reload/provider change or the Clear action. The selected provider
bills that visitor's account. Derived coordinates may go to the assistant;
genotype calls do not.

## Reproduce deployment

1. Apply `supabase/migrations/*.sql` to a dedicated Supabase project. Provision
   the two backend roles separately; keep passwords outside migrations. Set the
   auth Site URL to `https://stratalab.cc`, and allow only the exact owned workspace
   callback URLs used by this deployment. Configure Resend SMTP with sending-only
   access to `stratalab.cc`, sender `Strata <noreply@stratalab.cc>`, host
   `smtp.resend.com`, port 465, username `resend`, and the new Resend key as password.
2. Sign into Azure CLI in the protected student subscription. Create the standard
   environment using `environment.json` and ARM API `2026-07-01` explicitly. The
   `environmentMode: WorkloadProfiles` property is required: Express cannot host
   the event job or the custom domain. Keep only the Consumption workload profile.
3. Push to `main`. `.github/workflows/runtime-image.yml` publishes
   `ghcr.io/gothicscientist/strata-runtime:<commit>`. Use a public commit tag or
   immutable digest; do not deploy the moving `portfolio` tag automatically.
   For a digest, pass its source commit with `--git-sha`. Commit tags supply the
   source revision automatically so downloaded reports identify the deployed code.
4. Deploy with the authenticated CLI session:

   ```sh
   python infra/azure/deploy.py \
     --subscription YOUR_PROTECTED_SUBSCRIPTION_ID \
     --image ghcr.io/gothicscientist/strata-runtime:COMMIT_SHA
   ```

   A uv-installed Azure CLI on Windows may require
   `--az-python PATH/TO/azure-cli/Scripts/python.exe`. Normal browser login works
   with the Berkeley tenant; device-code login is blocked by its access policy.
   The script preserves existing hostname/certificate bindings during updates.
5. Set the frontend `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, and
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` in `apps/web/.env.local`. Run `pnpm build` in
   `apps/web` and wait for completion. This produces CSP headers matching those
   build-time origins. Then deploy the complete `out` directory:

   ```sh
   wrangler pages deploy apps/web/out --project-name strata-web \
     --branch <the project's production branch>
   ```

   Since November 3 this step is automatic: `.github/workflows/deploy-web.yml`
   builds and deploys on every push to `main` that touches `apps/web/`, using the
   repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. It asks
   Cloudflare for the production branch, so the deployment lands on stratalab.cc.

6. Bind `stratalab.cc` in Pages Custom domains. Cloudflare DNS should contain the
   apex CNAME to the assigned Pages hostname, the `api` CNAME to Azure (DNS only),
   the Azure `asuid.api` verification TXT, and Resend's DKIM/sending records.
   `www` is proxied and redirected to the apex with its path/query preserved.
   Nameservers at Spaceship are `anita.ns.cloudflare.com` and
   `cris.ns.cloudflare.com`; registration stays at Spaceship.

## Validation and maintenance

Run `python infra/azure/verify_live.py --url API_HTTPS_URL` after a deployment.
It creates synthetic guest fixtures, exercises all six analysis kinds, queue
scaling, examples, reports, comparisons, and isolation, then deletes its test
datasets/analyses. It never uses a person's DNA or an LLM key. The verification
report goes to `.deployment/live-verification.json`.

Email delivery/sign-in and a real billed AI tool call need separate browser
validation with the user's own inbox/key. A model provider mock passing does not
prove that the live account has credit or model access.

The November 1 Linux image run passed 570 tests, with one expected skip for the
missing-R error path. Its 700k-row timing test missed the threshold during the
busy full run, then passed in isolation. Web typecheck, 53 tests, and the production
build passed. Supabase's security advisor returned no lints. These checks do not
replace subsequent live deployment checks.

Live checks also covered ZIP/gzip, VCF, 23andMe, AncestryDNA, FTDNA, MyHeritage,
queued-job cancellation, and deletion. Browser validation covered raw upload,
QC, queued PCA, axis selection, persisted workspaces, and HTML/JSON downloads.
The QC display distinguishes the exact usable-SNP count from the coverage fraction.

For rollback, deploy the last known-good immutable image tag to both API and worker,
and restore the previous Pages deployment. Preserve the encryption key and database.
Review Azure's remaining credit and each free-plan quota before they expire.

The reference release has 193 populations, but its formal f2 cache covers 136. It
has no Andamanese-related/AASI proxy. The app must continue showing these limits;
deployment does not make unsupported population models scientifically identified.
