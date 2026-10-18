"""Offline safety tests for the one-time ISIR Radar locality pilot."""
import unittest
from unittest.mock import patch
from pilot.case_trial import (
    case_key, make_cases, pick_cases, pdf_url, candidate_pdf,
    extract_territory_names, execute,
)

URL="https://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=80660123"
MAPPING={
 "zruc nad sazavou":{("Kutná Hora","Zruč nad Sázavou")},
 "kutna hora":{("Kutná Hora","Kutná Hora")},
 "praha":{("Hlavní město Praha","Praha")},
}

def row(uid,spis,**kwargs):
    d={
      "id":uid,"spisova_znacka":spis,"popis_udalosti":"Dokument",
      "pdf_status":"ok","dokument_url":URL,
      "obsahuje_nemovitost":False,"katastralni_uzemi":[],
    }
    d.update(kwargs)
    return d

class PilotTests(unittest.TestCase):
    def test_exact_case_signature_is_not_invented(self):
        self.assertEqual(case_key(row(1,"INS 123/2026")),"INS 123/2026")
        self.assertEqual(case_key(row(2,"KSBR 30 INS 123/2026")),"KSBR 30 INS 123/2026")
        self.assertEqual(case_key(row(3,"garbled")),"")
        self.assertNotEqual(case_key(row(1,"INS 123/2026")),
                            case_key(row(2,"KSBR 30 INS 123/2026")))

    def sample(self):
        return {"updated_at":"test","items":[
          row(1,"INS 10/2026",obsahuje_nemovitost=True),
          row(2,"INS 10/2026",katastralni_uzemi=["Zruč nad Sázavou"]),
          row(3,"INS 20/2026",obsahuje_nemovitost=True),
          row(4,"INS 20/2026",popis_udalosti="Zpeněžení"),
          row(5,"INS 30/2026",obsahuje_nemovitost=True),
          row(6,"INS 99/2026",obsahuje_nemovitost=True,
              katastralni_uzemi=["Praha"]),
          row(7,"INCORRECT",obsahuje_nemovitost=True),
        ]}

    def test_groups_are_based_only_on_known_metadata(self):
        got=make_cases(self.sample(),MAPPING)
        self.assertEqual(len(got),3)
        by={r["spis"]:r for r in got}
        self.assertEqual(by["INS 10/2026"]["group"],
                         "other_documents_have_a_location")
        self.assertEqual(by["INS 10/2026"]["related_districts_mentioned"],
                         ["Kutná Hora"])
        self.assertEqual(by["INS 20/2026"]["group"],
                         "related_records_no_locality")
        self.assertEqual(by["INS 30/2026"]["group"],
                         "no_other_archived_records")

    def test_sample_is_deterministic_with_a_fixed_cap(self):
        cases=make_cases(self.sample(),MAPPING)
        a=pick_cases(cases,limit=2)
        b=pick_cases(cases,limit=2)
        self.assertEqual([x["spis"] for x in a],
                         [x["spis"] for x in b])
        self.assertEqual(len(a),2)

    def test_no_pdf_download_in_offline_metadata_mode(self):
        with patch("pilot.case_trial.inspect_pdf",
                   side_effect=AssertionError("PDF probe not allowed")):
            out=execute(self.sample(),MAPPING,scan_pdfs=False)
        self.assertEqual(out["sample_size"],3)
        self.assertEqual(out["pdf_probes"],[])
        self.assertFalse(out["case_linkage_verified"])
        self.assertFalse(out["property_sale_verified"])
        self.assertFalse(out["db_modified"])
        self.assertFalse(out["old_crawler_started"])

    def test_only_exact_official_document_links_allowed(self):
        self.assertEqual(pdf_url(URL),URL)
        for link in (
            "http://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=1",
            "https://isir.justice.cz.bad.invalid/isir_public_ws/doc/Document?idDokument=1",
            "https://example.com/x",
            "https://isir.justice.cz/isir/ueu/vysledek_lustrace.do",
            "https://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=oops",
            "https://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=1&x=2",
        ):
            with self.subTest(link=link), self.assertRaises(ValueError):
                pdf_url(link)

    def test_explicit_territory_context_required(self):
        text="Katastrální území Zruč nad Sázavou, okres Kutná Hora, LV 247"
        names=extract_territory_names(text,MAPPING)
        self.assertEqual(names,{"zruc nad sazavou"})
        self.assertEqual(extract_territory_names(
            "Ulice Zruč nad Sázavou, obec Zruč nad Sázavou",MAPPING),set())
        self.assertEqual(extract_territory_names(
            "katastrální území Praha",MAPPING),{"praha"})

    def test_one_candidate_pdf_from_related_records_before_fallback(self):
        r=make_cases(self.sample(),MAPPING)
        by={x["spis"]:x for x in r}
        self.assertEqual(candidate_pdf(by["INS 20/2026"])["id"],4)
        self.assertEqual(candidate_pdf(by["INS 30/2026"])["id"],5)

if __name__=="__main__":
    unittest.main()
