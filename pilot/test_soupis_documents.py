"""Offline contract tests for the real ISIR soupises pilot."""
import unittest

from pilot.soupis_documents import (
    category, choose, execute, safe_pdf_url, cadastral_names, page_asset_evidence, SELECT_CONTROL,
    SELECT_SOUPIS
)

ISIR="https://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=1234567"

def record(identifier, event, case, **kw):
    r={"id":identifier,"dokument_url":ISIR,
       "spisova_znacka":case,"popis_udalosti":event}
    r.update(kw)
    return r

class SelectionTests(unittest.TestCase):
    def test_document_type_not_inferred_from_real_estate_keyword_alone(self):
        self.assertEqual(category(record(1,"Soupis majetkové podstaty","INS 1/2026")),
                         "soupis_candidate")
        self.assertEqual(category(record(2,"Doplnění soupisu majetkové podstaty","INS 2/2026")),
                         "soupis_candidate")
        self.assertEqual(category(record(3,"Seznam přihlášených pohledávek","INS 3/2026")),
                         "control_candidate")
        self.assertEqual(category(record(4,"Sdělení věřitele","INS 4/2026")),
                         "control_candidate")
        self.assertEqual(category(record(5,"Nemovitost parcela 123/4","INS 5/2026")),
                         "")

    def test_only_official_public_documents_allowed(self):
        self.assertEqual(safe_pdf_url(ISIR),ISIR)
        for s in [
          "http://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=123",
          "https://isir.justice.cz.evil.test/isir_public_ws/doc/Document?idDokument=123",
          "https://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=1&x=2",
          "https://isir.justice.cz/isir/ueu/index.do",
          "",
        ]:
            with self.subTest(s=s),self.assertRaises(ValueError):
                safe_pdf_url(s)

    def test_unique_case_sampling_and_group_size_cap(self):
        source={"items":[
            record(1,"Soupis majetkové podstaty","INS 1/2026"),
            record(2,"Soupis majetkové podstaty","INS 1/2026"),
            record(3,"Doplnění soupisu majetkové podstaty","INS 2/2026"),
            record(4,"Seznam přihlášených pohledávek","INS 3/2026"),
            record(5,"Seznam přihlášených pohledávek","INS 4/2026"),
            record(6,"Soupis majetkové podstaty","INS 6/2026",
                   dokument_url="https://example.test/no.pdf"),
        ]}
        selected,counts=choose(source)
        self.assertEqual([x[1] for x in selected].count("soupis_candidate"),2)
        self.assertEqual([x[1] for x in selected].count("control_candidate"),2)
        self.assertEqual(len(selected),4)
        self.assertLessEqual(len(selected),SELECT_SOUPIS+SELECT_CONTROL)
        self.assertEqual(counts["soupis_candidate_eligible"],3)

    def test_cuzk_names_require_explicit_cadastral_context(self):
        mapping={
            "Zruč nad Sázavou":{("Kutná Hora","Zruč nad Sázavou")},
            "Praha":{("Hlavní město Praha","Praha")}
        }
        correct=cadastral_names(
            "Pozemek parc. č. 123/4 v katastrálním území Zruč nad Sázavou, "
            "list vlastnictví 456.", mapping)
        self.assertIn("zruc nad sazavou",correct)
        self.assertFalse(cadastral_names("Adresa Zruč nad Sázavou",mapping))

    def test_page_level_prevents_cross_page_false_link(self):
        mapping={"Zruč nad Sázavou":{("Kutná Hora","Zruč nad Sázavou")}}
        a=page_asset_evidence("katastrální území Zruč nad Sázavou",mapping,1)
        b=page_asset_evidence("parcela č. 123/4",mapping,2)
        self.assertEqual(a["target_district_mentions"],["Kutná Hora"])
        self.assertFalse(a["ku_parcel_same_page"])
        self.assertFalse(b["target_ku_parcel_same_page"])
        c=page_asset_evidence(
            "katastrální území Zruč nad Sázavou, parc. č. 123/4, LV 28",
            mapping,3)
        self.assertTrue(c["target_ku_parcel_same_page"])
        self.assertEqual(c["parcels_mentioned"],["123/4"])
        self.assertIn("28",c["lv_mentioned"])

    def test_pilot_does_not_automatically_claim_estate_asset_or_modify_db(self):
        data={"updated_at":"archive","items":[
            record(1,"Soupis majetkové podstaty","INS 1/2026"),
            record(2,"Sdělení věřitele","INS 2/2026")
        ]}
        report=execute(data,{},scan=False)
        self.assertEqual(report["selected_total"],2)
        self.assertTrue(report["conclusions_are_manual_review_pending"])
        self.assertFalse(report["db_modified"])
        self.assertFalse(report["legacy_crawler_started"])
        self.assertFalse(report["pdf_probing_enabled"])
        self.assertTrue(all(d["human_review_status"]=="not_reviewed"
                            for d in report["documents"]))

if __name__=="__main__":
    unittest.main()
