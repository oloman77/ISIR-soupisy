import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import crawler as c


class PriorityTests(unittest.TestCase):
    def candidate(self, i=1, version=10):
        return dict(id=i, dokument_url="test", obsahuje_nemovitost=True,
                    pdf_checked=True, pdf_status="ok", enrichment_version=version)

    def test_upgrades_only_candidates_without_location_version(self):
        row = self.candidate()
        self.assertTrue(c.pending_pdf(row))
        row["lokalita_version"] = 1
        self.assertFalse(c.pending_pdf(row))  # even when no region was found
        row.pop("lokalita_version")
        row["obsahuje_nemovitost"] = False
        self.assertFalse(c.pending_pdf(row))

    def test_priority_fairness_unique_and_retry(self):
        rows = {str(i): self.candidate(i) for i in range(1, 8)}
        rows.update({str(i): dict(id=i, dokument_url="test") for i in range(10, 20)})
        rows["30"] = dict(id=30, dokument_url="test")
        rows["31"] = dict(id=31)
        now = datetime.now(timezone.utc)
        rows["7"]["pdf_retry_after"] = (now + timedelta(hours=1)).isoformat()
        queue = c.analysis_queue(rows, list(rows), now, 10)
        self.assertEqual(queue[:7], ["1", "2", "11", "12", "13", "14", "10"])
        self.assertNotIn("7", queue)
        self.assertNotIn("31", queue)
        self.assertEqual(len(queue), len(set(queue)))
        self.assertIn("30", queue)

    def test_counts_exclude_missing_and_count_real_failures(self):
        rows = [self.candidate(), dict(id=2, pdf_status="no_url",
                poznamka="<p><priznakAnVedlejsiUdalost>T</priznakAnVedlejsiUdalost></p>"),
                dict(id=3, dokument_url="test", pdf_status="error:Timeout", pdf_attempts=1),
                dict(id=4, poznamka="broken")]
        counts = c.queue_counts(rows)
        self.assertEqual(counts["remaining_pdf_analysis"], 2)
        self.assertEqual(counts["pending_location"], 1)
        self.assertEqual(counts["failed_pdf_analysis"], 1)
        self.assertEqual(counts["pending_pdf_without_error"], 1)
        self.assertEqual(counts["missing_url_secondary_events"], 1)
        self.assertEqual(counts["missing_url_unclassified"], 1)

    def test_location_failure_retains_candidate_and_prior_details(self):
        row = self.candidate()
        row.update(kraj="Jihomoravský kraj", lv=["614"])
        with patch.object(c, "pdf_text", return_value=("", "error:Timeout")):
            c.refresh_location(row)
        self.assertTrue(row["obsahuje_nemovitost"])
        self.assertEqual(row["pdf_status"], "ok")
        self.assertEqual(row["lv"], ["614"])
        self.assertEqual(row["kraj"], "Jihomoravský kraj")
        self.assertTrue(c.needs_location(row))
        self.assertFalse(c.retry_due(row, datetime.now(timezone.utc)))

    def test_location_success_without_redetecting_or_resetting_version(self):
        row = self.candidate()
        text = "LV 614; Katastrální úřad pro Jihomoravský kraj, Katastrální pracoviště Břeclav"
        with patch.object(c, "pdf_text", return_value=(text, "ok")), patch.object(c, "detect_suspicion", side_effect=AssertionError):
            c.refresh_location(row)
        self.assertEqual(row["kraj"], "Jihomoravský kraj")
        self.assertFalse(c.needs_location(row))
        self.assertEqual(row["enrichment_version"], 10)

    def test_success_without_region_does_not_loop(self):
        row = self.candidate()
        with patch.object(c, "pdf_text", return_value=("bez určení lokality", "ok")):
            c.refresh_location(row)
        self.assertEqual(row["kraje"], [])
        self.assertFalse(c.pending_pdf(row))

    def test_old_candidate_is_priority_but_still_needs_ocr_upgrade(self):
        row = self.candidate(version=9)
        self.assertTrue(c.needs_analysis(row))
        self.assertTrue(c.needs_location(row))


if __name__ == "__main__":
    unittest.main()
