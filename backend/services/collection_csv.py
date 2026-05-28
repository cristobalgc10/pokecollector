import math


def normalize_collection_variant(variant: str | None) -> str:
    value = (variant or "").strip()
    return value or "Normal"


def is_valid_collection_purchase_price(purchase_price: float) -> bool:
    return math.isfinite(purchase_price) and purchase_price >= 0


def collection_import_key(card_id, variant, lang, condition, purchase_price):
    return (
        card_id,
        normalize_collection_variant(variant),
        lang or "en",
        condition,
        purchase_price,
    )


def merge_collection_import_item(items_by_key, key, item) -> bool:
    """Merge duplicate collection CSV rows before writing.

    Returns True when a new planned item was inserted, False when an existing
    planned item was incremented.
    """
    existing_item = items_by_key.get(key)
    if existing_item:
        existing_item.quantity += item.quantity or 1
        return False
    items_by_key[key] = item
    return True
