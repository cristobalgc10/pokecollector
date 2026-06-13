"""Helpers for optional digital-only TCGdex sets."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.orm import Session

from models import (
    BinderCard,
    Card,
    CollectionItem,
    CustomCardMatch,
    PriceHistory,
    ProductCard,
    ProductLedgerEntry,
    Set,
    Setting,
    WishlistItem,
)

DIGITAL_SETS_SETTING_KEY = "tcgdex_digital_sets_enabled"
DIGITAL_SERIES_IDS = {"tcgp"}


def setting_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "on"}


def digital_sets_enabled(db: Session) -> bool:
    row = db.query(Setting).filter(Setting.key == DIGITAL_SETS_SETTING_KEY).first()
    return setting_truthy(row.value if row else "false")


def purge_disabled_digital_catalogue(db: Session) -> dict[str, int]:
    if digital_sets_enabled(db):
        mark_existing_digital_rows(db)
        return {"sets_deleted": 0, "cards_deleted": 0}
    return purge_digital_catalogue(db)


def is_digital_set_data(set_data: Mapping[str, Any] | None) -> bool:
    if not set_data:
        return False

    serie = set_data.get("serie") or {}
    series_id = (
        set_data.get("_series_id")
        or (serie.get("id") if isinstance(serie, Mapping) else None)
    )
    if str(series_id or "").strip().lower() in DIGITAL_SERIES_IDS:
        return True

    for image_key in ("logo", "symbol"):
        value = str(set_data.get(image_key) or "").lower()
        if "/tcgp/" in value:
            return True

    return False


def mark_existing_digital_rows(db: Session) -> None:
    digital_set_rows = db.query(Set).filter(
        (
            (Set.is_digital == True)
            |
            (Set.series.ilike("%pocket%"))
            | (Set.images_logo.ilike("%/tcgp/%"))
            | (Set.images_symbol.ilike("%/tcgp/%"))
        )
    ).all()
    if not digital_set_rows:
        return

    for set_row in digital_set_rows:
        set_row.is_digital = True

    digital_pairs = {
        (set_row.tcg_set_id or set_row.id, set_row.lang or "en")
        for set_row in digital_set_rows
    }
    for set_id, lang in digital_pairs:
        db.query(Card).filter(Card.set_id == set_id, Card.lang == lang).update(
            {"is_digital": True},
            synchronize_session=False,
        )


def purge_digital_catalogue(db: Session) -> dict[str, int]:
    """Remove digital set/card catalogue rows and dependent user rows."""
    mark_existing_digital_rows(db)

    digital_set_ids = [row.id for row in db.query(Set.id).filter(Set.is_digital == True).all()]
    digital_card_ids = [row.id for row in db.query(Card.id).filter(Card.is_digital == True).all()]

    if not digital_set_ids and not digital_card_ids:
        return {"sets_deleted": 0, "cards_deleted": 0}

    if digital_card_ids:
        digital_product_card_ids = [
            row.id
            for row in db.query(ProductCard.id).filter(ProductCard.card_id.in_(digital_card_ids)).all()
        ]
        if digital_product_card_ids:
            db.query(ProductLedgerEntry).filter(
                ProductLedgerEntry.product_card_id.in_(digital_product_card_ids)
            ).update({"product_card_id": None}, synchronize_session=False)
        db.query(ProductLedgerEntry).filter(ProductLedgerEntry.card_id.in_(digital_card_ids)).update(
            {"card_id": None},
            synchronize_session=False,
        )
        db.query(CustomCardMatch).filter(CustomCardMatch.custom_card_id.in_(digital_card_ids)).delete(
            synchronize_session=False,
        )
        for model, column in (
            (BinderCard, BinderCard.card_id),
            (CollectionItem, CollectionItem.card_id),
            (WishlistItem, WishlistItem.card_id),
            (PriceHistory, PriceHistory.card_id),
            (ProductCard, ProductCard.card_id),
        ):
            db.query(model).filter(column.in_(digital_card_ids)).delete(synchronize_session=False)
        db.query(Card).filter(Card.id.in_(digital_card_ids)).delete(synchronize_session=False)

    if digital_set_ids:
        db.query(Set).filter(Set.id.in_(digital_set_ids)).delete(synchronize_session=False)

    return {"sets_deleted": len(digital_set_ids), "cards_deleted": len(digital_card_ids)}
