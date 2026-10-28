"""Real OpenRouter smoke test (opt-in, hits the real API; never runs in CI)."""

import os

import pytest
from openai import OpenAI

from ai_factory.infrastructure.openrouter_agent import OPENROUTER_BASE_URL

_REQUIRED_ENV = ("OPENROUTER_API_KEY", "OPENROUTER_MODEL")


@pytest.mark.integration
@pytest.mark.skipif(
    not all(os.environ.get(name) for name in _REQUIRED_ENV),
    reason="OpenRouter credentials are not configured",
)
def test_spec03_ac8_real_openrouter_chat_round_trip() -> None:
    """AC8: the configured OpenRouter model answers one chat completion."""
    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=os.environ["OPENROUTER_API_KEY"])

    completion = client.chat.completions.create(
        model=os.environ["OPENROUTER_MODEL"],
        messages=[{"role": "user", "content": "Reply with the single word OK."}],
        max_tokens=16,
    )

    content = completion.choices[0].message.content
    assert content is not None
    assert content.strip()
