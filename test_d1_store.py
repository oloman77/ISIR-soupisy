"""Offline regression tests: never contact Cloudflare or ISIR."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from d1_preflight import pack
from d1_store import D1Store, document_flags, public_candidate, unpack
from d1_migrate import source_records, migrate


class StoreTests(unittest.TestCase):
    def sample(self, rid=11):
        return {
            "id": rid,
            "datum_zverejneni": "2026-10-15T10:00:00+00:00",
            "dokument_url": "https://example.test/file.pdf",
            "pdf_checked": True, "pdf_status": "ok",
            "enrichment_version": 10, "lokalita_version": 1,
            "obsahuje_nemovitost": True, "spisova_znacka": "KSBR 1 INS 11/2026",
            "pdf_resume_text": "private OCR progress must not be published",
            "poznamka": "raw ISIR note excluded from public export",
        }

    def cloud(self, name="isir-prod"):
        cloud = Mock()
        cloud.request.return_value = {"name": name}
        cloud.query.return_value = []
        return cloud

    def test_lossless_checksum_roundtrip_and_corruption_detection(self):
        row = self.sample()
        packed, digest = pack(row)
        self.assertEqual(unpack(packed, digest), row)
        with self.assertRaises(RuntimeError):
            unpack(packed, "0" * 64)

    def test_public_export_keeps_candidate_but_drops_raw_working_fields(self):
        row = public_candidate(self.sample())
        self.assertEqual(row["id"], 11)
        self.assertNotIn("pdf_resume_text", row)
        self.assertNotIn("poznamka", row)
        self.assertNotIn("enrichment_version", row)

    def test_queue_flags_and_candidate_flags(self):
        done = self.sample()
        self.assertEqual(document_flags(done), (1, 0))
        pending = dict(done, pdf_checked=False, pdf_status="error:Timeout")
        self.assertEqual(document_flags(pending), (0, 1))
        location = dict(done, lokalita_version=0)
        self.assertEqual(document_flags(location), (1, 1))
        missing = dict(done, dokument_url=None)
        self.assertEqual(document_flags(missing), (0, 0))

    def test_dedicated_production_database_guard(self):
        with self.assertRaisesRegex(RuntimeError, "target mismatch"):
            D1Store(cloud=self.cloud("isir-test"))
        self.assertIsNotNone(D1Store(cloud=self.cloud("isir-prod")))

    def test_missing_checkpoint_fails_closed(self):
        store = D1Store(cloud=self.cloud())
        with self.assertRaisesRegex(RuntimeError, "no verified crawler checkpoint"):
            store.require_state()

    def test_upserts_are_bounded_and_digest_checked(self):
        cloud = self.cloud()
        store = D1Store(cloud=cloud)
        store.upsert_documents(self.sample(i) for i in range(1, 24))
        calls = cloud.query.call_args_list
        self.assertEqual(len(calls), 3)
        for call in calls:
            sql, params = call.args
            self.assertIn("ON CONFLICT(id)", sql)
            self.assertLessEqual(len(params), 60)
            self.assertIn("digest<>excluded.digest", sql)

    def test_load_documents_verifies_remote_digests(self):
        cloud = self.cloud()
        item = self.sample()
        payload, digest = pack(item)
        cloud.query.side_effect = [
            [{"id": item["id"], "payload": payload, "digest": digest}],
        ]
        store = D1Store(cloud=cloud)
        cutoff = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.assertEqual(store.load_documents(cutoff), {str(item["id"]): item})

    def test_import_filters_retention_and_detects_duplicates(self):
        now = datetime(2026, 10, 18, tzinfo=timezone.utc)
        old = dict(self.sample(12), datum_zverejneni="2026-01-01T00:00:00Z")
        chosen, expected, expired = source_records(
            {"items": [self.sample(), old]}, now - timedelta(days=90))
        self.assertEqual(len(chosen), 1)
        self.assertEqual(set(expected), {11})
        self.assertEqual(expired, 1)
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            source_records({"items": [self.sample(), self.sample()]},
                           now - timedelta(days=90))

    def test_failed_migration_cannot_publish_checkpoint(self):
        now = datetime(2026, 10, 18, tzinfo=timezone.utc)
        store = Mock()
        store.get_state.return_value = None
        store.upsert_documents.side_effect = RuntimeError("write failed")
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            migrate(store, {"items": [self.sample()]},
                    {"current_id": 11}, now)
        store.save_state.assert_not_called()

    def test_successful_migration_publishes_checkpoint_last(self):
        now = datetime(2026, 10, 18, tzinfo=timezone.utc)
        store = Mock()
        store.get_state.return_value = None
        store.verify_import.return_value = 1
        state = {"current_id": 11, "days_back": 90}
        migrate(store, {"items": [self.sample()]}, state, now)
        store.save_state.assert_called_once_with(state)
        self.assertLess(
            store.method_calls.index(store.verify_import({11: pack(self.sample())[1]})),
            store.method_calls.index(store.save_state(state)),
        )

    def test_live_crawler_uses_d1_checkpoint_and_publishes_candidates_only(self):
        import crawler as c
        import d1_store
        now = datetime.now(timezone.utc)
        candidate = self.sample()
        candidate["datum_zverejneni"] = now.isoformat()
        pending = dict(self.sample(12),
                       datum_zverejneni=now.isoformat(),
                       pdf_checked=False, pdf_status="error:Timeout",
                       obsahuje_nemovitost=False)
        store = Mock()
        store.require_state.return_value = {
            "current_id": 100, "all_documents_from_id": 90,
            "days_back": 90, "backfill_complete": True,
        }
        store.load_documents.return_value = {"11": candidate, "12": pending}
        saved = {}
        with patch.object(c, "USE_D1", True), patch.object(c, "DAYS_BACK", 90), \
             patch.object(c, "MAX_PDF_PER_RUN", 0), \
             patch.object(d1_store, "D1Store", return_value=store), \
             patch.object(c, "get_last_id", return_value=100), \
             patch.object(c, "save_json", side_effect=lambda path, val: saved.setdefault(str(path), val)):
            c.main()
        published = saved[str(c.RESULTS_FILE)]
        self.assertEqual(len(published["items"]), 1)
        self.assertNotIn("pdf_resume_text", published["items"][0])
        self.assertEqual(published["remaining_pdf_analysis"], 1)
        self.assertNotIn(str(c.STATE_FILE), saved)
        store.save_state.assert_called_once()
        store.prune_expired.assert_called_once()


if __name__ == "__main__":
    unittest.main()
