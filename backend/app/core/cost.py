"""Token to USD cost accounting.

Prices are approximate DeepSeek list prices (USD per 1M tokens) and are easy to update.
The mechanism, not the exact number, is the point: every run reports its cost.
"""

PRICES = {
    "deepseek-chat": {"in": 0.27, "out": 1.10},
    "deepseek-reasoner": {"in": 0.55, "out": 2.19},
}
_FALLBACK = {"in": 0.50, "out": 1.50}


def summarize_cost(usage_by_model: dict) -> dict:
    """Turn LangChain usage metadata {model: {input_tokens, output_tokens}} into a cost summary."""
    in_tok = out_tok = 0
    usd = 0.0
    for model, u in (usage_by_model or {}).items():
        i = int(u.get("input_tokens", 0))
        o = int(u.get("output_tokens", 0))
        price = PRICES.get(model, _FALLBACK)
        usd += i / 1_000_000 * price["in"] + o / 1_000_000 * price["out"]
        in_tok += i
        out_tok += o
    return {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "usd": round(usd, 6),
        "by_model": usage_by_model or {},
    }
