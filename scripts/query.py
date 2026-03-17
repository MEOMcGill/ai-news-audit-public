"""Reusable module to query all four AI providers.

Usage:
    from query import query_all, query_one, MODELS

    # Query all four models with the same prompt
    results = query_all("What happened in Canada today?")

    # Query a single model
    text = query_one("openai", "What happened in Canada today?")
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Cheapest non-reasoning model for each provider
MODELS = {
    "openai": {
        "name": "GPT-5-mini",
        "model_id": "gpt-5-mini",
        "input_per_mtok": 0.25,
        "output_per_mtok": 2.00,
        "knowledge_cutoff": "2024-05-31",
    },
    "gemini": {
        "name": "Gemini 3 Flash",
        "model_id": "gemini-3-flash-preview",
        "input_per_mtok": 0.50,
        "output_per_mtok": 3.00,
        "knowledge_cutoff": "2025-01-01",
    },
    "xai": {
        "name": "Grok 4 Fast",
        "model_id": "grok-4-fast-non-reasoning",
        "input_per_mtok": 0.20,
        "output_per_mtok": 0.50,
        "knowledge_cutoff": "2024-11-01",
    },
    "anthropic": {
        "name": "Claude Haiku 4.5",
        "model_id": "claude-haiku-4-5-20251001",
        "input_per_mtok": 1.00,
        "output_per_mtok": 5.00,
        "knowledge_cutoff": "2025-02-01",
    },
}


_clients = {}


def _get_openai_client():
    if "openai" not in _clients:
        from openai import OpenAI
        _clients["openai"] = OpenAI()
    return _clients["openai"]


def _get_xai_client():
    if "xai" not in _clients:
        from openai import OpenAI
        _clients["xai"] = OpenAI(
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
        )
    return _clients["xai"]


def _get_gemini_client():
    if "gemini" not in _clients:
        from google import genai
        _clients["gemini"] = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _clients["gemini"]


def _get_anthropic_client():
    if "anthropic" not in _clients:
        import anthropic
        _clients["anthropic"] = anthropic.Anthropic()
    return _clients["anthropic"]


def query_one(provider: str, prompt: str, system: str | None = None, max_tokens: int = 4096) -> str:
    """Query a single provider. Returns the response text."""
    if provider == "openai":
        client = _get_openai_client()
        input_messages = []
        if system:
            input_messages.append({"role": "system", "content": system})
        input_messages.append({"role": "user", "content": prompt})
        r = client.responses.create(
            model=MODELS["openai"]["model_id"],
            input=input_messages,
            reasoning={"effort": "minimal"},
            max_output_tokens=max_tokens,
        )
        return r.output_text

    elif provider == "gemini":
        client = _get_gemini_client()
        contents = prompt
        if system:
            contents = f"{system}\n\n{prompt}"
        r = client.models.generate_content(
            model=MODELS["gemini"]["model_id"],
            contents=contents,
        )
        return r.text

    elif provider == "xai":
        client = _get_xai_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        r = client.chat.completions.create(
            model=MODELS["xai"]["model_id"],
            messages=messages,
            max_tokens=max_tokens,
        )
        return r.choices[0].message.content

    elif provider == "anthropic":
        client = _get_anthropic_client()
        kwargs = {
            "model": MODELS["anthropic"]["model_id"],
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        r = client.messages.create(**kwargs)
        return r.content[0].text

    else:
        raise ValueError(f"Unknown provider: {provider}")


def query_all(prompt: str, system: str | None = None, max_tokens: int = 4096) -> dict[str, str]:
    """Query all four providers with the same prompt. Returns {provider: response_text}."""
    results = {}
    for provider in MODELS:
        try:
            results[provider] = query_one(provider, prompt, system=system, max_tokens=max_tokens)
        except Exception as e:
            results[provider] = f"ERROR: {e}"
    return results


if __name__ == "__main__":
    # Smoke test
    print("=== Smoke Test: query_all ===\n")
    results = query_all('Reply "hello"', max_tokens=16)
    for provider, text in results.items():
        status = "✓" if not text.startswith("ERROR") else "✗"
        print(f"  {status} {MODELS[provider]['name']:25s} → {text.strip()}")
