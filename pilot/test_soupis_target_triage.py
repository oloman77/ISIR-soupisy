"""Offline separation of target cadastral evidence and generic regional mentions."""
import unittest
from pilot.soupis_target_triage import triage

LINK="https://isir.justice.cz:8443/isir_public_ws/doc/Document?idDokument=123"
MAPPING={
 "zruc nad sazavou":{("Kutná Hora","Zruč nad Sázavou")},
 "havlickuv brod":{("Havlíčkův Brod","Havlíčkův Brod")},
 "praha":{("Hlavní město Praha","Praha")},
}
def row(uid,**kwargs):
    r={"id":uid,"popis_udalosti":"Soupis majetkové podstaty",
       "dokument_url":LINK,"spisova_znacka":f"INS {uid}/2026"}
    r.update(kwargs)
    return r

class TargetTriageTests(unittest.TestCase):
    def test_distinguishes_exact_district_from_region_only(self):
        src={"items":[
          row(1,katastralni_uzemi=["Zruč nad Sázavou"]),
          row(2,katastralni_uzemi=["Havlíčkův Brod"]),
          row(3,kraje=["Středočeský kraj"]),
        ]}
        # Do not accept generic region as a district-level evidence.
        out=triage(src,MAPPING)
        c=out["selection_counts"]
        self.assertEqual(c["target_cadastral_mention"],2)
        self.assertEqual(c["target_region_mention_only"],1)
        self.assertEqual(len(out["target_cadastral_document_leads"]),2)
        self.assertEqual(len(out["target_region_only_document_leads"]),1)
        self.assertTrue(all(not r["asset_in_estate_verified"]
                            for r in out["target_cadastral_document_leads"]))
        self.assertTrue(out["no_database_writes"])
        self.assertFalse(out["old_crawler_started"])

    def test_other_district_and_nongeo_do_not_masquerade_as_leads(self):
        data={"items":[
          row(1,katastralni_uzemi=["Praha"]),
          row(2),
          row(3,kraje=["Moravskoslezský kraj"]),
          {**row(4,katastralni_uzemi=["Zruč nad Sázavou"]),
           "popis_udalosti":"Přihláška pohledávky"},
        ]}
        report=triage(data,MAPPING)
        self.assertEqual(report["selection_counts"]["soupis_metadata_pdf_links"],3)
        self.assertEqual(report["selection_counts"]["other_district_cadastral_mentions"],1)
        self.assertEqual(report["selection_counts"]["no_geographic_metadata"],1)
        self.assertEqual(report["selection_counts"]["other_region_only"],1)
        self.assertFalse(report["target_cadastral_document_leads"])

if __name__=="__main__":
    unittest.main()
