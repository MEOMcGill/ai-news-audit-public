"""Flagship model query module — upgraded models for robustness check.

Same interface as query.py but uses top-tier models:
  OpenAI:    GPT-5.2
  Gemini:    Gemini 3 Pro (initially 2.5 Pro; upgraded mid-collection)
  xAI:       Grok 4
  Anthropic: Claude Sonnet 4.6
"""

import os
import time
from dotenv import load_dotenv

load_dotenv()

MODELS = {
    "openai": {
        "name": "GPT-5.2",
        "model_id": "gpt-5.2",
        "input_per_mtok": 2.00,
        "output_per_mtok": 8.00,
        "knowledge_cutoff": "2025-08-31",
    },
    "gemini": {
        "name": "Gemini 3 Pro",
        "model_id": "gemini-3-pro-preview",
        "input_per_mtok": 1.25,
        "output_per_mtok": 10.00,
        "knowledge_cutoff": "2025-01-31",
    },
    "xai": {
        "name": "Grok 4",
        "model_id": "grok-4",
        "input_per_mtok": 3.00,
        "output_per_mtok": 10.00,
        "knowledge_cutoff": "2024-11-30",
    },
    "anthropic": {
        "name": "Claude Sonnet 4.6",
        "model_id": "claude-sonnet-4-20250514",
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "knowledge_cutoff": "2025-03-01",
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


def query_one(provider: str, prompt: str, system: str | None = None, max_tokens: int = 4096, retries: int = 3) -> str:
    """Query a single provider with retry on rate limits. Returns the response text."""
    for attempt in range(retries + 1):
        try:
            return _query_one_impl(provider, prompt, system, max_tokens)
        except Exception as e:
            err_str = str(e)
            is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "rate" in err_str.lower()
            if is_rate_limit and attempt < retries:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                time.sleep(wait)
                continue
            raise


def _query_one_impl(provider: str, prompt: str, system: str | None = None, max_tokens: int = 4096) -> str:
    if provider == "openai":
        client = _get_openai_client()
        input_messages = []
        if system:
            input_messages.append({"role": "system", "content": system})
        input_messages.append({"role": "user", "content": prompt})
        r = client.responses.create(
            model=MODELS["openai"]["model_id"],
            input=input_messages,
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
