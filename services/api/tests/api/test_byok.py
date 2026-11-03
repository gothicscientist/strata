"""Request-scoped credentials must never enter the persisted chat audit."""

from __future__ import annotations

import json

import pytest

from strata.api.schemas import ChatMessageCreate


def test_byok_isolated_and_not_persisted(client, make_guest, monkeypatch):
    import strata.agent as agent

    clients = []

    class Provider:
        closed = False

        async def close(self):
            self.closed = True

    def make_provider(name, model, *, api_key):
        provider = Provider()
        clients.append((name, model, api_key, provider))
        return provider

    async def stream(history, content, *, provider, **kwargs):
        assert provider is clients[-1][3]
        yield {"type": "text_delta", "text": "Test response"}
        yield {"type": "done", "answer": "Test response", "citations": []}

    monkeypatch.setattr(agent, "get_provider", make_provider)
    monkeypatch.setattr(agent, "stream_chat", stream)
    headers = make_guest(client)
    sid = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
    for provider, key in (("openai", "test-key-first"), ("anthropic", "test-key-second")):
        result = client.post(
            f"/api/v1/chat/sessions/{sid}/messages",
            headers=headers,
            json={"content": "Test", "provider": provider, "api_key": key, "model": "test-model"},
        )
        assert result.status_code == 200, result.text
        assert key not in result.text
    assert [c[:3] for c in clients] == [
        ("openai", "test-model", "test-key-first"),
        ("anthropic", "test-model", "test-key-second"),
    ]
    assert all(c[3].closed for c in clients)
    history = client.get(f"/api/v1/chat/sessions/{sid}", headers=headers).text
    assert "test-key" not in history and "api_key" not in history
    assert client.get("/api/v1/health").json()["capabilities"]["llm_byok"]


def test_byok_secret_excluded_and_invalid_provider_rejected(client, make_guest):
    body = ChatMessageCreate(content="hello", api_key="private-key-123")
    assert "private-key-123" not in repr(body)
    assert "api_key" not in body.model_dump()
    headers = make_guest(client)
    sid = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
    response = client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        headers=headers,
        json={"content": "hello", "provider": "other", "api_key": "private-key-123"},
    )
    assert response.status_code == 422
    assert "private-key-123" not in response.text


@pytest.mark.asyncio
async def test_provider_errors_do_not_expose_credentials():
    from strata.agent.providers import OpenAIProvider, ProviderSettings

    class RejectedError(Exception):
        status_code = 401

    class Completions:
        async def create(self, **kwargs):
            raise RejectedError("private-key-123")

    class Client:
        chat = type("Chat", (), {"completions": Completions()})()

    provider = OpenAIProvider(ProviderSettings(model="test-model"), client=Client())
    events = [e async for e in provider.stream(system="test", tools=[], messages=[])]
    text = json.dumps([e.model_dump(mode="json") for e in events])
    assert "private-key-123" not in text
    assert "rejected your API key" in text
