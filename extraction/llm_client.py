"""Thin wrapper over the OpenAI-compatible Qwen endpoint.

Every call returns the same dict shape, including token usage and the USD
cost, so callers never have to reach for the raw response object.
"""

import time

from openai import OpenAI

from extraction import pricing
from extraction.config import QWEN_API_KEY, QWEN_BASE_URL

_client = None


def client():
    if not QWEN_API_KEY:
        raise RuntimeError("QWEN_API_KEY is not set; add it to .env")
    global _client
    if _client is None:
        _client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    return _client


def chat(model, system, user, temperature=0.0, json_object=False):
    started = time.time()
    result = {
        "model": model,
        "text": "",
        "error": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0,
        "latency_s": 0.0,
    }

    kwargs = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_object:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = client().chat.completions.create(**kwargs)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["latency_s"] = round(time.time() - started, 2)
        return result

    usage = response.usage
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0

    result["text"] = (response.choices[0].message.content or "").strip()
    result["prompt_tokens"] = prompt_tokens
    result["completion_tokens"] = completion_tokens
    result["cost_usd"] = pricing.cost_usd(model, prompt_tokens, completion_tokens)
    result["latency_s"] = round(time.time() - started, 2)
    return result
