"""Offline unit tests for bounded 6+3 review, no remote services."""
import unittest
from unittest.mock import patch
from pilot.audit_six_plus_three import (
  SIX,FAILED,IDS,identify_rows,fetch_pdf,page_evidence,inspect,execute
)

def row(uid,typ="Soupis majetkové podstaty"):
    return {"id":uid,"popis_udalosti":typ,"spisova_znacka":"INS 111/2026",
      "dokument_url":"https://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=124",
      "katastralni_uzemi":["Kutná Hora"]}

class ReviewTests(unittest.TestCase):
    def test_scope_only_six_and_three(self):
        self.assertEqual(len(SIX),6)
        self.assertEqual(len(FAILED),3)
        self.assertEqual(len(IDS),9)
        self.assertEqual(len(set(IDS)),9)
        r=identify_rows({"items":[row(uid) for uid in reversed(IDS)]})
        self.assertEqual([int(x["id"]) for x in r],list(IDS))

    def test_missing_source_is_fail_closed(self):
        with self.assertRaises(RuntimeError):
            identify_rows({"items":[row(uid) for uid in SIX]})

    def test_page_evidence_requires_explicit_cadastral_wording(self):
        lookup={"Kutná Hora":{("Kutná Hora","Kutná Hora")}}
        a=page_evidence("Soupis majetkové podstaty: "
            "katastrální území Kutná Hora, parc. č. 123/4, LV 56",1,lookup)
        self.assertIn("kutna hora",a["cadastral_names"])
        self.assertEqual(a["district_mentions"],["Kutná Hora"])
        self.assertIn("123/4",a["parcels_mentioned"])
        self.assertIn("56",a["lv_mentioned"])
        self.assertTrue(a["ku_and_parcel_same_page"])
        b=page_evidence("Dlužník má adresu Kutná Hora, parc. 11",2,lookup)
        self.assertFalse(b["ku_and_parcel_same_page"])
        self.assertEqual(b["cadastral_names"],[])

    def test_oversized_pdf_is_not_fetched_in_full(self):
        r=row(FAILED[0])
        class Headers(dict):
            pass
        class Response:
            status=200
            url=r["dokument_url"]
            headers=Headers({"Content-Length":"30000000"})
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self,*a):raise AssertionError("should not download over cap")
        with patch("pilot.audit_six_plus_three.urlopen",return_value=Response()):
            payload,meta=fetch_pdf(r)
        self.assertIsNone(payload)
        self.assertEqual(meta["error_code"],"too_large_reported")

    def test_aggregate_report_does_not_propose_database_modification(self):
        src={"updated_at":"fixture","items":[row(uid) for uid in IDS]}
        with patch("pilot.audit_six_plus_three.inspect",
                   side_effect=lambda r,_,ocr:{
                     "source_id":r["id"],"analysis_status":"ok",
                     "cadastral_mention_pages":[1],
                     "same_page_ku_parcel_count":0,
                     "target_district_mentions":[],"ocr_succeeded":0}):
            out=execute(src,{})
        self.assertEqual(out["count"],9)
        self.assertTrue(out["no_database_writes"])
        self.assertTrue(out["no_crawler"])
        self.assertTrue(out["no_ownership_inferences"])
        self.assertEqual(out["successful"],9)

if __name__=="__main__":
    unittest.main()
