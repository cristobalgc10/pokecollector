import unittest
import datetime

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base
    from models import (
        Binder,
        BinderCard,
        Card,
        CollectionItem,
        CustomCardMatch,
        ProductCard,
        ProductLedgerEntry,
        ProductPurchase,
        Set,
        Setting,
        User,
        WishlistItem,
    )
    from services.digital_sets import is_digital_set_data, purge_digital_catalogue, purge_disabled_digital_catalogue
    from services.pokemon_api import parse_card_for_db, parse_set_for_db
    API_TEST_DEPS_AVAILABLE = True
except ModuleNotFoundError:
    API_TEST_DEPS_AVAILABLE = False


@unittest.skipUnless(API_TEST_DEPS_AVAILABLE, "Backend dependencies are not installed in this lightweight test environment")
class DigitalSetTests(unittest.TestCase):
    def test_tcgp_series_sets_are_marked_digital(self):
        parsed = parse_set_for_db({
            "id": "A1",
            "name": "Genetic Apex",
            "serie": {"id": "tcgp", "name": "Pokemon TCG Pocket"},
            "cardCount": {"official": 226, "total": 286},
        })

        self.assertTrue(parsed["is_digital"])

    def test_tcgp_cards_inherit_digital_flag_from_embedded_set(self):
        parsed = parse_card_for_db({
            "id": "A1-001",
            "name": "Bulbasaur",
            "localId": "001",
            "set": {"id": "A1", "serie": {"id": "tcgp", "name": "Pokemon TCG Pocket"}},
        }, lang="en")

        self.assertTrue(parsed["is_digital"])

    def test_physical_sets_are_not_marked_digital(self):
        self.assertFalse(is_digital_set_data({
            "id": "sv01",
            "name": "Scarlet & Violet",
            "serie": {"id": "sv", "name": "Scarlet & Violet"},
        }))

    def test_purge_detaches_product_ledger_and_deletes_custom_matches(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            user = User(username="ash", hashed_password="x", role="trainer", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

            product = ProductPurchase(
                product_name="Pocket booster",
                user_id=user.id,
                product_type="Booster",
                purchase_price=4.99,
                purchase_date=datetime.date(2026, 1, 1),
            )
            db.add(product)
            db.flush()

            db.add(Set(id="A1_en", tcg_set_id="A1", name="Genetic Apex", lang="en", is_digital=True))
            db.add(Card(id="A1-1_en", tcg_card_id="A1-1", name="Digital", set_id="A1", lang="en", is_digital=True))
            db.flush()

            product_card = ProductCard(
                product_id=product.id,
                user_id=user.id,
                card_id="A1-1_en",
                initial_quantity=1,
                active_quantity=1,
            )
            db.add(product_card)
            db.flush()

            ledger = ProductLedgerEntry(
                product_card_id=product_card.id,
                product_id=product.id,
                user_id=user.id,
                entry_type="card_sale",
                card_id="A1-1_en",
                quantity=1,
                amount=5.0,
                event_date=datetime.date(2026, 1, 2),
                card_name="Digital",
            )
            db.add(ledger)
            db.add(CustomCardMatch(custom_card_id="A1-1_en", api_card_id="A1-1", status="pending"))
            db.commit()

            result = purge_digital_catalogue(db)
            db.commit()

            self.assertEqual(result, {"sets_deleted": 1, "cards_deleted": 1})
            self.assertEqual(db.query(Set).count(), 0)
            self.assertEqual(db.query(Card).count(), 0)
            self.assertEqual(db.query(ProductCard).count(), 0)
            self.assertEqual(db.query(CustomCardMatch).count(), 0)
            ledger_row = db.query(ProductLedgerEntry).one()
            self.assertIsNone(ledger_row.card_id)
            self.assertIsNone(ledger_row.product_card_id)
            self.assertEqual(ledger_row.card_name, "Digital")
        finally:
            db.close()

    def test_disabled_startup_cleanup_purges_legacy_pocket_user_rows(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            user = User(username="misty", hashed_password="x", role="trainer", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

            db.add(Setting(key="tcgdex_digital_sets_enabled", value="false"))
            db.add(Set(
                id="A1_en",
                tcg_set_id="A1",
                name="Genetic Apex",
                series="Pokemon TCG Pocket",
                lang="en",
                is_digital=False,
            ))
            db.add(Card(
                id="A1-1_en",
                tcg_card_id="A1-1",
                name="Digital",
                set_id="A1",
                lang="en",
                is_digital=False,
            ))
            db.flush()

            collection_item = CollectionItem(card_id="A1-1_en", user_id=user.id, quantity=1, lang="en")
            binder = Binder(name="Pocket Binder", user_id=user.id, binder_type="wishlist")
            db.add(collection_item)
            db.add(WishlistItem(card_id="A1-1_en", user_id=user.id, quantity=1))
            db.add(binder)
            db.flush()
            db.add(BinderCard(
                binder_id=binder.id,
                card_id="A1-1_en",
                collection_item_id=collection_item.id,
                required_quantity=1,
            ))
            db.commit()

            result = purge_disabled_digital_catalogue(db)
            db.commit()

            self.assertEqual(result, {"sets_deleted": 1, "cards_deleted": 1})
            self.assertEqual(db.query(Set).count(), 0)
            self.assertEqual(db.query(Card).count(), 0)
            self.assertEqual(db.query(CollectionItem).count(), 0)
            self.assertEqual(db.query(WishlistItem).count(), 0)
            self.assertEqual(db.query(BinderCard).count(), 0)
            self.assertEqual(db.query(Binder).count(), 1)
        finally:
            db.close()

    def test_enabled_startup_cleanup_marks_legacy_pocket_rows_without_purging(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            db.add(Setting(key="tcgdex_digital_sets_enabled", value="true"))
            db.add(Set(
                id="A1_en",
                tcg_set_id="A1",
                name="Genetic Apex",
                series="Pokemon TCG Pocket",
                lang="en",
                is_digital=False,
            ))
            db.add(Card(
                id="A1-1_en",
                tcg_card_id="A1-1",
                name="Digital",
                set_id="A1",
                lang="en",
                is_digital=False,
            ))
            db.commit()

            result = purge_disabled_digital_catalogue(db)
            db.commit()

            self.assertEqual(result, {"sets_deleted": 0, "cards_deleted": 0})
            self.assertEqual(db.query(Set).count(), 1)
            self.assertEqual(db.query(Card).count(), 1)
            self.assertTrue(db.query(Set).one().is_digital)
            self.assertTrue(db.query(Card).one().is_digital)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
