"""What a proof-reading run is about to cost, and what it did cost.

The estimate exists so a mistake in a script cannot quietly spend money, and the
measured figure exists so the estimate can be checked against reality.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import BackendUsage

#: USD per million tokens: (input, output, cached input). Output includes the
#: thinking tokens a reasoning model bills.
#:
#: Verified against Google's published rates in September 2026. The Flash rates
#: below are introductory and are scheduled to double on 1 January 2027, so treat
#: a cost printed after that date as a floor, not a quote.
PRICES: dict[str, tuple[float, float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-3.7-flash": (0.75, 3.75, 0.075),
    "gemini-3.6-flash": (0.75, 3.75, 0.075),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.03),
    "gemini-3-flash": (0.50, 3.00, 0.05),
    "gemini-3-flash-lite": (0.25, 1.50, 0.025),
}

PRICES_VALID_UNTIL = "2026-12-31"

#: Characters per token. Finnish packs fewer characters into a token than English
#: does, so the two languages are counted separately.
_CHARS_PER_TOKEN: dict[str, float] = {"fi": 3.2, "et": 3.2, "hu": 3.2}
_DEFAULT_CHARS_PER_TOKEN = 4.0

#: What to assume the model will write back before it has written anything: a
#: few patches plus the thinking tokens a medium reasoning level spends.
ASSUMED_OUTPUT_TOKENS = 4_000
ASSUMED_THINKING_TOKENS = 10_000


@dataclass
class CostEstimate:
    prompt_tokens: int
    output_tokens: int
    cost_usd: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 4),
        }


def normalize_model(model: str) -> str:
    model = (model or "").strip()
    if model.startswith("models/"):
        model = model.split("/", 1)[1]
    return model.split("@")[0]


def estimate_tokens(text: str, lang: str = "") -> int:
    """Rough token count for a block of text, without calling the API."""
    base = (lang or "").strip().lower().split("-")[0]
    divisor = _CHARS_PER_TOKEN.get(base, _DEFAULT_CHARS_PER_TOKEN)
    return int(len(text) / divisor) + 1


def estimate(
    prompt_text: str,
    model: str,
    *,
    source_lang: str = "",
    calls: int = 1,
) -> CostEstimate:
    """Cost of a run that has not happened yet.

    The prompt is mixed source and target text, so it is counted at the denser of
    the two rates. Over-counting here is the safe direction: it can only make the
    guard fire early, never late.
    """
    prompt_tokens = estimate_tokens(prompt_text, source_lang or "fi") * max(calls, 1)
    output_tokens = (ASSUMED_OUTPUT_TOKENS + ASSUMED_THINKING_TOKENS) * max(calls, 1)

    prices = PRICES.get(normalize_model(model))
    if prices is None:
        return CostEstimate(prompt_tokens, output_tokens, None)

    input_price, output_price, _ = prices
    cost = (prompt_tokens * input_price + output_tokens * output_price) / 1_000_000
    return CostEstimate(prompt_tokens, output_tokens, cost)


def compute_cost(usage: BackendUsage, model: str) -> float | None:
    """Cost of a run that has happened, from the provider's own token counts."""
    prices = PRICES.get(normalize_model(model))
    if prices is None:
        return None

    input_price, output_price, cached_price = prices
    fresh_prompt = max(usage.prompt_tokens - usage.cached_tokens, 0)
    billed_output = usage.output_tokens + usage.thoughts_tokens

    cost = (
        fresh_prompt * input_price
        + usage.cached_tokens * cached_price
        + billed_output * output_price
    ) / 1_000_000
    return cost
