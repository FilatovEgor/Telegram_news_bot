import asyncio
import json
from types import SimpleNamespace

import pytest

from app.ai.agent import EditorialAgent


def package_json():
    return json.dumps(
        {
            "category": "economy",
            "language": "en",
            "summary": "Gazprom reported a 15% increase in exports in 2024.",
            "key_points": ["Exports increased by 15% in 2024."],
            "entities": ["Gazprom"],
            "important_numbers": ["15%", "2024"],
            "channel_variants": {
                "telegram": "Gazprom reported a 15% increase in exports in 2024.",
                "brief": "Gazprom exports rose 15% in 2024.",
            },
            "caveats": [],
            "confidence": 0.85,
        }
    )


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0
        self.max_tokens = []

    async def create_chat_completion(self, **kwargs):
        self.calls += 1
        self.max_tokens.append(kwargs["max_completion_tokens"])
        if self.calls == 1:
            arguments = json.dumps({"text": "one two three", "max_words": 5})
            call = SimpleNamespace(
                id="tool-1",
                function=SimpleNamespace(name="check_word_count", arguments=arguments),
                model_dump=lambda exclude_none=True: {
                    "id": "tool-1",
                    "type": "function",
                    "function": {"name": "check_word_count", "arguments": arguments},
                },
            )
            message = SimpleNamespace(content=None, tool_calls=[call])
        else:
            message = SimpleNamespace(content=package_json(), tool_calls=[])
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=120)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=usage,
        )


def test_editorial_agent_runs_tools_and_returns_structured_package():
    provider = FakeProvider()
    result = asyncio.run(
        EditorialAgent(provider).create_editorial_package(
            "Gazprom exports", "Gazprom reported a 15% increase in 2024.", "https://example.com/news"
        )
    )
    assert result.package.category == "economy"
    assert result.package.channel_variants.brief.startswith("Gazprom")
    assert result.tool_trace[0]["tool"] == "check_word_count"
    assert result.tool_trace[0]["success"] is True
    assert result.attempt_count == 2
    assert result.input_tokens == 200
    assert result.output_tokens == 240
    assert provider.calls == 2


class RateLimitError(Exception):
    status_code = 429


class RetryingProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.failed_once = False

    async def create_chat_completion(self, **kwargs):
        if not self.failed_once:
            self.failed_once = True
            raise RateLimitError("slow down")
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=package_json(), tool_calls=[]))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=80),
        )


@pytest.mark.asyncio
async def test_editorial_agent_retries_rate_limits_with_bounded_attempts(monkeypatch):
    waits = []

    async def no_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    provider = RetryingProvider()
    result = await EditorialAgent(provider, retry_attempts=1).create_editorial_package(
        "Gazprom exports", "Gazprom reported a 15% increase in 2024.", "https://example.com/news"
    )
    assert result.attempt_count == 2
    assert waits == [0.5]


def test_editorial_agent_rejects_input_over_configured_character_budget():
    provider = FakeProvider()
    agent = EditorialAgent(provider, max_input_chars=5)
    with pytest.raises(ValueError, match="character limit"):
        asyncio.run(
            agent.create_editorial_package(
                "Title", "This article is too long", "https://example.com/news"
            )
        )
    assert provider.calls == 0


def test_editorial_agent_rejects_invalid_structured_response():
    provider = FakeProvider()
    async def invalid_response(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not json", tool_calls=[]))],
            usage=None,
        )

    provider.create_chat_completion = invalid_response
    with pytest.raises(ValueError, match="JSON editorial package"):
        asyncio.run(
            EditorialAgent(provider, max_tool_rounds=0).create_editorial_package(
                "Title", "Article content", "https://example.com/news"
            )
        )


@pytest.mark.asyncio
async def test_ai_concurrency_limiter_caps_global_and_workload_requests():
    from app.ai.concurrency import AIConcurrencyLimiter

    limiter = AIConcurrencyLimiter(
        max_concurrent_requests=2,
        max_editorial_concurrency=1,
        max_translation_concurrency=1,
    )
    active_total = 0
    active_by_workload = {"editorial": 0, "translation": 0}
    max_total = 0
    max_by_workload = {"editorial": 0, "translation": 0}

    async def run_request(workload):
        nonlocal active_total, max_total
        async with limiter.slot(workload):
            active_total += 1
            active_by_workload[workload] += 1
            max_total = max(max_total, active_total)
            max_by_workload[workload] = max(
                max_by_workload[workload],
                active_by_workload[workload],
            )
            await asyncio.sleep(0.01)
            active_by_workload[workload] -= 1
            active_total -= 1

    await asyncio.gather(
        *(run_request("editorial") for _ in range(5)),
        *(run_request("translation") for _ in range(5)),
    )
    assert max_total == 2
    assert max_by_workload == {"editorial": 1, "translation": 1}


@pytest.mark.asyncio
async def test_ai_retry_releases_concurrency_slot_during_backoff(monkeypatch):
    from app.ai.concurrency import AIConcurrencyLimiter

    backoff_started = asyncio.Event()
    release_backoff = asyncio.Event()
    second_provider_call_started = asyncio.Event()

    class TrackingRetryProvider(RetryingProvider):
        async def create_chat_completion(self, **kwargs):
            if self.failed_once:
                second_provider_call_started.set()
            return await super().create_chat_completion(**kwargs)

    provider = TrackingRetryProvider()
    limiter = AIConcurrencyLimiter(
        max_concurrent_requests=1,
        max_editorial_concurrency=1,
        max_translation_concurrency=1,
    )
    agent = EditorialAgent(provider, retry_attempts=1, concurrency_limiter=limiter)

    async def controlled_sleep(_seconds):
        backoff_started.set()
        await release_backoff.wait()

    monkeypatch.setattr(asyncio, "sleep", controlled_sleep)
    first = asyncio.create_task(
        agent.create_editorial_package("Title A", "Article A", "https://example.com/a")
    )
    await backoff_started.wait()

    second = asyncio.create_task(
        agent.create_editorial_package("Title B", "Article B", "https://example.com/b")
    )
    await asyncio.wait_for(second_provider_call_started.wait(), timeout=1)
    release_backoff.set()
    await asyncio.gather(first, second)
