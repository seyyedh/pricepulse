"""Bubble (premium over intrinsic value) of the IME deposit certificates.

bubble % = (certificate price - intrinsic value) / intrinsic value, with the intrinsic value
of one certificate unit from the domestic gold market or the global price at the free-market
dollar rate:

- Gold bar: 0.1 g of 995 gold, valued from the price of a gram of 18k (750) gold.
- Silver bar: 1 g of 999 silver, from the global ounce price.
- Copper cathode, zinc ingot: 1 kg, from the LME price per ton. (Not COMEX: Iran's domestic
  copper is priced off LME, and COMEX carries a US premium.)
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from sources import tgju

logger = logging.getLogger(__name__)

TROY_OUNCE_GRAMS = 31.1035
GOLD_CERT_GRAMS = 0.1
GOLD_CERT_PURITY = 995
GOLD_18K_PURITY = 750


@dataclass(frozen=True)
class Bubble:
    name: str
    pct: float


async def _lme_copper_per_ton() -> float | None:
    # The copper in the price list is COMEX; LME comes from tgju (already fetched, so cached)
    try:
        return (await tgju.fetch_price("base_global_copper", timedelta(days=3))).price
    except Exception as e:
        logger.warning("No LME copper price for the copper bubble: %s", e)
        return None


async def get_bubbles(prices: dict[str, float]) -> list[Bubble]:
    """Bubbles computable from prices (asset key -> price, in Toman or USD as in the list)."""
    usd = prices.get("usd")
    lme_copper = await _lme_copper_per_ton()

    def per_kg(usd_per_ton: float | None) -> float | None:
        return usd_per_ton / 1000 * usd if usd_per_ton and usd else None

    intrinsic = {
        "ime_gold": (
            prices["gold18"] * GOLD_CERT_PURITY / GOLD_18K_PURITY * GOLD_CERT_GRAMS
            if "gold18" in prices else None
        ),
        "ime_silver": prices["xag"] / TROY_OUNCE_GRAMS * usd if "xag" in prices and usd else None,
        "ime_copper": per_kg(lme_copper),
        "ime_zinc": per_kg(prices.get("zinc")),
    }
    names = {
        "ime_gold": "حباب سپرده شمش طلا",
        "ime_silver": "حباب سپرده نقره",
        "ime_copper": "حباب سپرده مس",
        "ime_zinc": "حباب سپرده روی",
    }
    bubbles = []
    for key, value in intrinsic.items():
        cert = prices.get(key)
        if cert and value:
            bubbles.append(Bubble(names[key], (cert - value) / value * 100))
    return bubbles
