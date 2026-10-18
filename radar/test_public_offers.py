"""Offline tests for the first geographically validated public offer import."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from radar.import_legacy import normal
from radar.import_public_offers import SOURCE_FILE, validate, build_statements


class PublicOfferTests(unittest.TestCase):
    def setUp(self):
        self.item=json.loads(SOURCE_FILE.read_text(encoding="utf-8"))["items"][0]
        self.mapping={normal("Vilémovice u Ledče nad Sázavou"):
                      {("Havlíčkův Brod","Vilémovice")}}
        self.today=date(2026,10,18)

    def valid(self, item=None):
        return validate(item or self.item,self.mapping,self.today)

    def test_verified_geographic_reference_and_price(self):
        r=self.valid()
        self.assertEqual(r["district"],"Havlíčkův Brod")
        self.assertEqual(r["cadastral_territory"],"Vilémovice u Ledče nad Sázavou")
        self.assertEqual(r["parcel"],"27, 414/10, 709")
        self.assertEqual(r["lv"],"264")
        self.assertEqual(r["area_m2"],660)
        self.assertEqual(r["price_czk"],314000)
        self.assertEqual(r["id"],"sale:portaldrazeb:6y4")

    def test_rejects_false_positive_geography(self):
        for correction in (
            {"district":"Kutná Hora"},
            {"municipality":"Vilémovice u Prahy"},
            {"cadastral_territory":"Vilémovice"},
            {"source_url":"https://evil.example/insolvencni-zamer/6y4"},
            {"source_url":"https://www.portaldrazeb.cz/insolvencni-zamer/6y4?redirect=bad"},
            {"source":"unknown"},
        ):
            with self.subTest(correction=correction),self.assertRaises(ValueError):
                self.valid({**self.item,**correction})

    def test_expired_listing_requires_manual_review_not_silent_publishing(self):
        with self.assertRaises(ValueError):
            validate(self.item,self.mapping,date(2027,1,1))
        with self.assertRaises(ValueError):
            self.valid({**self.item,"checked_at":"2026-10-19"})

    def test_inserts_idempotently_preserving_user_decisions_and_original(self):
        db=sqlite3.connect(":memory:")
        db.executescript(Path("radar/schema.sql").read_text(encoding="utf-8"))
        r=self.valid()
        sqls=build_statements(r)
        for sql,args in sqls:
            db.execute(sql,args)
        db.execute("INSERT INTO property_decisions (property_id,title_override,status,note) "
                   "VALUES (?,?,?,?)",(r["id"],"Můj upravený název","watching",
                                     "Ověřit cenu u správce"))
        db.commit()
        for sql,args in sqls:
            db.execute(sql,args)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM properties").fetchone()[0],1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM property_sources").fetchone()[0],1)
        self.assertEqual(db.execute(
            "SELECT title_override,status,note FROM property_decisions").fetchone(),
            ("Můj upravený název","watching","Ověřit cenu u správce"))
        self.assertEqual(db.execute(
            "SELECT price_czk FROM property_sources").fetchone()[0],314000)
        self.assertEqual(db.execute("SELECT sale_phase FROM properties").fetchone()[0],
                         "listed")
        self.assertEqual(db.execute(
            "SELECT COUNT(*) FROM decision_history").fetchone()[0],0)
        db.close()

    def test_pilot_import_never_updates_any_user_fields(self):
        for sql,_ in build_statements(self.valid()):
            self.assertIn("ON CONFLICT(id) DO NOTHING",sql)
            self.assertNotIn("UPDATE SET",sql)
            self.assertNotIn("property_decisions",sql)
            self.assertNotIn("decision_history",sql)


if __name__=="__main__":
    unittest.main()
