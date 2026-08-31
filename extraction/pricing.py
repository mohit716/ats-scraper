"""Token pricing for the models used here.

Rates are Alibaba Cloud Model Studio *international* list prices in USD per
million tokens, verified against
https://www.alibabacloud.com/help/en/model-studio/model-pricing (Aug 2026).
Mainland-China endpoints are billed differently and are not modelled.
"""

USD_PER_MILLION = {
    "qwen-flash": {"input": 0.05, "output": 0.40},
    "qwen-turbo": {"input": 0.05, "output": 0.20},
    "qwen-plus": {"input": 0.40, "output": 1.20},
    "qwen-max": {"input": 1.60, "output": 6.40},
}

# Anything unrecognised is priced as qwen-plus so an unknown model shows a
# plausible non-zero cost rather than silently reporting free.
FALLBACK = USD_PER_MILLION["qwen-plus"]


def rate_for(model):
    if not model:
        return FALLBACK
    if model in USD_PER_MILLION:
        return USD_PER_MILLION[model]
    # Dated snapshots look like "qwen-flash-2025-07-28".
    for name, rate in USD_PER_MILLION.items():
        if model.startswith(name):
            return rate
    return FALLBACK


def cost_usd(model, prompt_tokens=0, completion_tokens=0):
    rate = rate_for(model)
    return (
        prompt_tokens * rate["input"] + completion_tokens * rate["output"]
    ) / 1_000_000


def known_models():
    return sorted(USD_PER_MILLION)
