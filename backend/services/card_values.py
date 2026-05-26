VALID_PRICE_FIELDS = {"price_market", "price_trend", "price_avg1", "price_avg7", "price_avg30", "price_low"}
PRICE_PRIMARY_TO_FIELD = {
    "market": "price_market",
    "avg": "price_market",
    "trend": "price_trend",
    "avg1": "price_avg1",
    "avg7": "price_avg7",
    "avg30": "price_avg30",
    "low": "price_low",
}
HOLO_VARIANTS = {"Holo", "Holo Rare", "Holo V", "Holo VMAX", "Holo VSTAR", "Holo ex", "Reverse Holo"}
HOLO_FIELD_MAP = {
    "price_market": "price_market_holo",
    "price_trend": "price_trend_holo",
    "price_avg1": "price_avg1_holo",
    "price_avg7": "price_avg7_holo",
    "price_avg30": "price_avg30_holo",
    "price_low": "price_low_holo",
}


def normalize_price_field(price_field: str | None) -> str:
    if not price_field:
        return "price_trend"
    value = str(price_field)
    field = PRICE_PRIMARY_TO_FIELD.get(value, value)
    return field if field in VALID_PRICE_FIELDS else "price_trend"


def effective_market_price(card, variant=None, price_field: str | None = "price_trend") -> float:
    """Return the selected Cardmarket EUR price for a card, using holo prices for holo variants."""
    if not card:
        return 0
    field = normalize_price_field(price_field)
    if variant in HOLO_VARIANTS:
        holo_field = HOLO_FIELD_MAP.get(field)
        if holo_field and getattr(card, holo_field, None) is not None:
            return getattr(card, holo_field) or 0
    return getattr(card, field, None) or getattr(card, "price_market", None) or 0
