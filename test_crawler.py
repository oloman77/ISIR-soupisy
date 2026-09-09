import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import crawler as c


class MonitoringTests(unittest.TestCase):
    def test_old_failed_documents_are_retried(self):
        self.assertTrue(c.needs_analysis({'pdf_checked': True, 'pdf_status': 'no_text', 'enrichment_version': 9}))
        self.assertFalse(c.needs_analysis({'pdf_checked': True, 'pdf_status': 'ok', 'enrichment_version': 10}))

    def test_missing_urls_do_not_consume_processing_slots(self):
        rows = {"1": {"id": 1, "pdf_status": "no_url"},
                "2": {"id": 2, "dokument_url": "test"}}
        self.assertEqual(c.analysis_queue(rows, list(rows), datetime.now(timezone.utc), 0), ["2"])

    def test_current_documents_and_backlog_both_get_slots(self):
        rows = {str(i): {"id": i, "dokument_url": "test"} for i in range(1, 11)}
        queue = c.analysis_queue(rows, list(rows), datetime.now(timezone.utc), 2)
        self.assertEqual(queue[:5], ["3", "4", "5", "6", "1"])
        self.assertEqual(set(queue), set(rows))
        self.assertEqual(len(queue), len(rows))

    def test_partial_pdf_resumes_after_last_completed_page(self):
        response = SimpleNamespace(content=b"%PDF-fixture", raise_for_status=lambda: None)
        calls = []
        def page(n):
            def extract():
                calls.append(n)
                return ("page " + str(n) + " ") * 30
            return SimpleNamespace(extract_text=extract)
        progress = {}
        reader = SimpleNamespace(pages=[page(1), page(2)])
        with patch.object(c.SESSION, "get", return_value=response), patch.object(c, "PdfReader", return_value=reader), patch.object(c.time, "monotonic", side_effect=[0, 1, 121]):
            _, status = c.pdf_text("test", progress)
        self.assertEqual(status, "partial:time_limit")
        self.assertEqual(progress["pdf_resume_page"], 1)
        with patch.object(c.SESSION, "get", return_value=response), patch.object(c, "PdfReader", return_value=reader):
            text, status = c.pdf_text("test", progress)
        self.assertEqual(status, "ok")
        self.assertEqual(calls, [1, 2])
        self.assertIn("page 1", text)
        self.assertIn("page 2", text)

    def test_changed_pdf_restarts_progress(self):
        response = SimpleNamespace(content=b"%PDF-new", raise_for_status=lambda: None)
        progress = {"pdf_resume_page": 9, "pdf_resume_text": "OLD", "pdf_resume_sha256": "old"}
        reader = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: "NEW " * 30)])
        with patch.object(c.SESSION, "get", return_value=response), patch.object(c, "PdfReader", return_value=reader):
            text, status = c.pdf_text("test", progress)
        self.assertEqual(status, "ok")
        self.assertNotIn("OLD", text)
        self.assertIn("NEW", text)

    def test_retry_backoff(self):
        now = datetime.now(timezone.utc)
        self.assertFalse(c.retry_due({'pdf_retry_after': (now + timedelta(hours=1)).isoformat()}, now))
        self.assertTrue(c.retry_due({}, now))

    def test_failed_read_is_not_complete(self):
        with patch.object(c, 'pdf_text', return_value=('', 'error:Timeout')):
            row = c.enrich({'dokument_url': 'test'})
        self.assertFalse(row['pdf_checked'])
        self.assertEqual(row['review_status'], 'unread')
        self.assertIsNotNone(row['pdf_retry_after'])

    def test_mixed_pdf_ocr_and_pages_after_40(self):
        pages = [SimpleNamespace(extract_text=lambda: 'ordinary text ' * 20) for _ in range(40)]
        pages.append(SimpleNamespace(extract_text=lambda: ''))
        response = SimpleNamespace(content=b'%PDF-fixture', raise_for_status=lambda: None)
        def command(args, **kwargs):
            return SimpleNamespace(stdout=b'pozemek parc. 123 list vlastnictvi 45')
        with patch.object(c.SESSION, 'get', return_value=response), patch.object(c, 'PdfReader', return_value=SimpleNamespace(pages=pages)), patch.object(c.subprocess, 'run', side_effect=command) as run:
            text, status = c.pdf_text('test')
        self.assertEqual(status, 'ok')
        self.assertIn('123', text)
        self.assertEqual(run.call_count, 2)
        self.assertIn('41', run.call_args_list[0].args[0])

    def test_ocr_failure_is_visible(self):
        response = SimpleNamespace(content=b'%PDF-fixture', raise_for_status=lambda: None)
        with patch.object(c.SESSION, 'get', return_value=response), patch.object(c, 'PdfReader', return_value=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: '')])), patch.object(c.subprocess, 'run', side_effect=FileNotFoundError):
            _, status = c.pdf_text('test')
        self.assertEqual(status, 'error:FileNotFoundError')

    def test_isir_link_uses_case_number(self):
        url = c.isir_search_url({'spisova_znacka': 'KSBR 12 INS 1234/2026'})
        self.assertIn('bc_vec=1234', url)
        self.assertIn('rocnik=2026', url)

    def test_new_non_inventory_document_is_collected(self):
        now = datetime.now(timezone.utc)
        event = {'id': 101, 'datum_zverejneni': now.isoformat(), 'dokument_url': 'test', 'popis_udalosti': 'Zpráva správce'}
        saved = {}
        def save(path, obj):
            saved[str(path)] = obj
        with patch.object(c, 'load_json', side_effect=[{'current_id': 100, 'days_back': 180, 'backfill_complete': True}, {'items': []}]), patch.object(c, 'get_last_id', return_value=101), patch.object(c, 'get_after_id', return_value=[event]), patch.object(c, 'pdf_text', return_value=('', 'no_text')), patch.object(c, 'save_json', side_effect=save), patch.object(c.time, 'sleep'):
            c.main()
        results = saved[str(c.RESULTS_FILE)]
        self.assertEqual(results['count_all_documents'], 1)
        self.assertEqual(results['count_all_soupisy'], 0)
        self.assertEqual(results['remaining_pdf_analysis'], 1)
        self.assertEqual(results['failed_pdf_analysis'], 1)
        self.assertEqual(results['all_documents_from_id'], 100)
        self.assertEqual(results['phase'], 'pdf_analysis')


if __name__ == '__main__':
    unittest.main()
