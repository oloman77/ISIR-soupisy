"""Offline tests; never contact Cloudflare or ISIR."""
import json
import sqlite3
import unittest
from pathlib import Path

from radar.import_legacy import normal, inferred_location, relevant, candidates


ROOT = Path(__file__).resolve().parent
SCHEMA = (ROOT / "radar/schema.sql").read_text(encoding="utf-8")


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.addCleanup(self.db.close)

    def row(self, **change):
        data = {
            "id": 12, "obsahuje_nemovitost": True, "pdf_status": "ok",
            "dokument_url": "https://example.test/pdf", "katastralni_uzemi": ["Zruč nad Sázavou"],
            "kraje": ["Středočeský kraj"],
        }
        data.update(change)
        return data

    def test_db_schema_and_manual_decisions_are_independent(self):
        self.db.execute("INSERT INTO properties(id,title,district) VALUES (?,?,?)",
                        ("isir-doc:12", "Document found", "Kutná Hora"))
        self.db.execute("INSERT INTO property_decisions(property_id,status,note,tags_json) VALUES (?,?,?,?)",
                        ("isir-doc:12", "watching", "Price to be verified", '["u vody"]'))
        self.db.execute("UPDATE properties SET title=? WHERE id=?",
                        ("Updated automatic description", "isir-doc:12"))
        self.assertEqual(self.db.execute(
            "SELECT status,note,tags_json FROM property_decisions WHERE property_id=?",
            ("isir-doc:12",)).fetchone(),
            ("watching", "Price to be verified", '["u vody"]'))

    def test_foreign_keys_reject_decisions_without_property(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO property_decisions(property_id) VALUES (?)",
                            ("missing",))

    def test_status_domain_and_default(self):
        self.db.execute("INSERT INTO properties(id,title) VALUES (?,?)", ("1","Test"))
        self.assertEqual(self.db.execute("SELECT district FROM properties WHERE id='1'").fetchone()[0], "")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO property_decisions(property_id,status) VALUES (?,?)",
                            ("1","invalid"))

    def test_geo_name_normalizes_accents(self):
        self.assertEqual(normal("Žďár nad Sázavou"), "zdar nad sazavou")

    def test_geography_target_outside_ambiguous(self):
        mapping={
            normal("Zruč nad Sázavou"): {("Kutná Hora","Zruč nad Sázavou")},
            normal("Dobrá Voda"): {("Havlíčkův Brod","Dobrá Voda")},
            normal("Praha"): {("Hlavní město Praha","Praha")},
            normal("Nová Ves"): {("Kolín","Nová Ves"),("Kutná Hora","Nová Ves")}
        }
        a=inferred_location(self.row(),mapping)
        self.assertEqual(a,("Kutná Hora","Zruč nad Sázavou","suggested"))
        self.assertTrue(relevant(self.row(),a))
        b=inferred_location(self.row(katastralni_uzemi=["Praha"]),mapping)
        self.assertFalse(relevant(self.row(katastralni_uzemi=["Praha"]),b))
        c=inferred_location(self.row(katastralni_uzemi=["Nová Ves"]),mapping)
        self.assertEqual(c,("","","unknown"))
        self.assertTrue(relevant(self.row(katastralni_uzemi=["Nová Ves"]),c))

    def test_candidate_filters_only_pdf_suspicions(self):
        lookup={normal("Zruč nad Sázavou"):{("Kutná Hora","Zruč nad Sázavou")}}
        data={"items":[self.row(),self.row(id=13,pdf_status="no_text"),
                      self.row(id=14,obsahuje_nemovitost=False)]}
        got=list(candidates(data,lookup))
        self.assertEqual([r["id"] for r,_ in got],[12])

    def test_portal_never_uses_legacy_results_as_runtime_storage(self):
        api=(ROOT/"functions/api/properties.js").read_text()
        self.assertNotIn("docs/results.json",api)
        middleware=(ROOT/"functions/_middleware.js").read_text()
        self.assertIn("crypto.subtle.verify",middleware)
        self.assertIn("RADAR_ALLOWED_EMAIL",middleware)
        self.assertIn("await context.next()",middleware)


if __name__ == "__main__":
    unittest.main()
