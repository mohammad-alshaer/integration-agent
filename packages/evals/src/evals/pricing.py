"""Per-provider, per-model pricing tables for converting tokens -> dollars.

Prices are USD per 1 million tokens, sourced from each provider's public pricing
page as of 2026-04-27. Update as providers change pricing — these are not
contractually fixed.
"""

from __future__ import annotations

# (provider, model) -> (input_price_per_million, output_price_per_million) in USD
PRICING: dict[tuple[str, str], tuple[float, float]] = {
    # Google Gemini (paid tier-1 standard pricing as of Apr 2026)
    ("gemini", "gemini-2.5-flash"): (0.075, 0.30),
    ("gemini", "gemini-2.5-pro"): (1.25, 5.00),
    ("gemini", "gemini-embedding-001"): (0.025, 0.0),
    # Anthropic Claude 4.x family
    ("claude", "claude-haiku-4-5"): (1.00, 5.00),
    ("claude", "claude-sonnet-4-6"): (3.00, 15.00),
    ("claude", "claude-opus-4-7"): (15.00, 75.00),
    # Test fixtures
    ("fake", "fake-1"): (0.0, 0.0),
}


def price_per_million(provider: str, model: str) -> tuple[float, float]:
    """Return (input_price, output_price) per 1M tokens. Falls back to (0.0, 0.0) for unknowns."""
    key = (provider, model)
    if key in PRICING:
        return PRICING[key]
    # Try a normalized model match (strip trailing date suffixes like '-20251001')
    base_model = model.rsplit("-", 1)[0] if "-" in model else model
    return PRICING.get((provider, base_model), (0.0, 0.0))


def tokens_to_dollars(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> tuple[float, float, float]:
    """Return (input_dollars, output_dollars, total_dollars) for the supplied token counts."""
    in_per_m, out_per_m = price_per_million(provider, model)
    in_dollars = tokens_in * in_per_m / 1_000_000
    out_dollars = tokens_out * out_per_m / 1_000_000
    return in_dollars, out_dollars, in_dollars + out_dollars


__all__ = ["PRICING", "price_per_million", "tokens_to_dollars"]
