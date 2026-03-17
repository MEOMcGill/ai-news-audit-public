"""Quick smoke test for all four API keys."""

import os
from dotenv import load_dotenv

load_dotenv()

MODELS = {
    "OpenAI (GPT-5-mini)": {
        "key_var": "OPENAI_API_KEY",
        "model": "gpt-5-mini",
    },
    "Google (Gemini 2.5 Flash)": {
        "key_var": "GEMINI_API_KEY",
        "model": "gemini-2.5-flash",
    },
    "xAI (Grok 3)": {
        "key_var": "XAI_API_KEY",
        "model": "grok-3-beta",
    },
    "Anthropic (Claude Haiku 4.5)": {
        "key_var": "ANTHROPIC_API_KEY",
        "model": "claude-haiku-4-5-20251001",
    },
}

TEST_PROMPT = "Say 'hello' in one word."


def test_openai():
    from openai import OpenAI
    client = OpenAI()
    r = client.responses.create(
        model="gpt-5-mini",
        input=TEST_PROMPT,
    )
    return r.output_text


def test_gemini():
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    r = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=TEST_PROMPT,
    )
    return r.text


def test_xai():
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["XAI_API_KEY"],
        base_url="https://api.x.ai/v1",
    )
    r = client.chat.completions.create(
        model="grok-3-beta",
        messages=[{"role": "user", "content": TEST_PROMPT}],
        max_tokens=10,
    )
    return r.choices[0].message.content


def test_anthropic():
    import anthropic
    client = anthropic.Anthropic()
    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": TEST_PROMPT}],
    )
    return r.content[0].text


def main():
    # Check keys are set
    print("=== API Key Check ===\n")
    all_set = True
    for name, cfg in MODELS.items():
        key = os.environ.get(cfg["key_var"], "")
        status = "SET" if key else "MISSING"
        if not key:
            all_set = False
        print(f"  {name:35s} ${cfg['key_var']:20s} {status}")

    if not all_set:
        print("\n⚠  Fill in missing keys in .env, then re-run.")
        return

    # Test each API
    print("\n=== API Smoke Tests ===\n")
    tests = [
        ("OpenAI (GPT-5-mini)", test_openai),
        ("Google (Gemini 2.5 Flash)", test_gemini),
        ("xAI (Grok 3)", test_xai),
        ("Anthropic (Claude Haiku 4.5)", test_anthropic),
    ]
    for name, fn in tests:
        try:
            result = fn()
            print(f"  ✓ {name:35s} → {result.strip()}")
        except Exception as e:
            print(f"  ✗ {name:35s} → {e}")


if __name__ == "__main__":
    main()
