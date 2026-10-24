"""Deterministic tests of bounded ISIR metadata pilot; no network."""
from datetime import datetime,timezone,timedelta
from xml.etree import ElementTree as ET
import unittest

from pilot.metadata_7d_live import (
  SERVICE, MAX_CALLS, MIN_SOAP_INTERVAL_SECONDS, SAMPLE_ID_LOOKBACK,
  local, child_text, classify, parse_actions, analyze, execute
)

def xmltip(n):
    return ET.fromstring('<root><cisloPosledniId>'+str(n)+'</cisloPosledniId></root>')

def xmlrows(rows):
    d='<root>'
    for rid,date,typ,desc,url,case in rows:
        d+=('<data><id>'+str(rid)+'</id>'
            '<datumZverejneniUdalosti>'+date+'</datumZverejneniUdalosti>'
            '<typUdalosti>'+str(typ)+'</typUdalosti>'
            '<popisUdalosti>'+desc+'</popisUdalosti>'
            '<dokumentUrl>'+url+'</dokumentUrl>'
            '<spisovaZnacka>'+case+'</spisovaZnacka></data>')
    return ET.fromstring(d+'</root>')

class MetadataTests(unittest.TestCase):
    def test_lexical_categories_not_verified_asset(self):
        cases=[
          ("Soupis majetkové podstaty","puvodni_soupis_kandidat"),
          ("Doplnění soupisu majetkové podstaty","doplneni_soupisu"),
          ("Oprava soupisu majetkové podstaty","oprava_zmena_soupisu"),
          ("Výzva k předložení soupisu majetkové podstaty","nejednoznacny_soupis"),
          ("Zpeněžení majetkové podstaty","dalsi_majetkove_udalosti"),
          ("Zpráva insolvenčního správce","nejednoznacny_majetkovy_dokument"),
          ("Změna osoby","ostatni")
        ]
        for s,category in cases:
            with self.subTest(s=s):
                self.assertEqual(classify(s),category)

    def test_actual_fields_and_no_personal_notes_retained(self):
        sample=xmlrows([(100,"2026-10-22T14:00:00Z","321",
            "Soupis majetkové podstaty","https://isir.justice.cz/x",
            "INS 1/2013")])
        rows=parse_actions(sample)
        self.assertEqual(rows[0]["id"],100)
        self.assertEqual(rows[0]["case_year"],"2013")
        self.assertEqual(rows[0]["type"],"321")
        self.assertFalse("poznamka" in rows[0])
        self.assertFalse("spisova_znacka" in rows[0])

    def test_sample_does_not_claim_complete_week(self):
        end=datetime(2026,10,24,19,0,0,tzinfo=timezone.utc)
        records=parse_actions(xmlrows([
          (88,"2026-10-24T17:00:00Z","10","Soupis majetkové podstaty",
           "https://isir.justice.cz/doc/1","INS 2/2018"),
          (89,"2026-10-24T18:00:00Z","20","Doplnění soupisu majetkové podstaty",
           "https://isir.justice.cz/doc/1","INS 4/2015"),
          (90,"2026-10-24T18:15:00Z","30","Změna osoby","","INS 2/2017")
        ]))
        r=analyze(records,end-timedelta(days=7),end,{"loaded":False},{},
                  {"id_at_initial_probe":90,"transport_ok":True})
        self.assertEqual(r["status"],"PARTIAL_NOT_SEVEN_DAY_TOTAL")
        self.assertFalse(r["completeness"]["covers_start"])
        self.assertIsNone(r["estimated_seven_day_pdf_count"])
        self.assertEqual(r["observed_sample_not_week_total"]["unique_document_urls"],1)
        self.assertEqual(r["observed_sample_not_week_total"]["events_without_document_url"],1)
        self.assertEqual(r["observed_sample_not_week_total"]["old_case_year_events"],3)
        self.assertFalse(r["codes"][0]["official_code_verified"])

    def test_two_calls_with_ten_minutes_advance_no_more(self):
        now=datetime(2026,10,24,19,0,0,tzinfo=timezone.utc)
        calls=[]
        clock=[0.]
        def transport(xml):
            calls.append(xml)
            if "PosledniId" in xml: return xmltip(1000),123
            return xmlrows([(950,"2026-10-24T18:30:00Z",
                "111","Soupis majetkové podstaty",
                "https://isir.justice.cz/doc/123","INS 12/2013")]),456
        def wait(n):
            self.assertGreaterEqual(n,MIN_SOAP_INTERVAL_SECONDS)
            clock[0]+=n
        import unittest.mock
        with unittest.mock.patch("pilot.metadata_7d_live.time.monotonic",
                                 side_effect=lambda:clock[0]):
            result=execute(clock=now,wait=wait,transport=transport,
                           catalog_fetch=lambda:({"loaded":False},{}))
        self.assertEqual(len(calls),MAX_CALLS)
        self.assertEqual(result["request_limits"]["requested_after_id"],
                         1000-SAMPLE_ID_LOOKBACK)
        self.assertEqual(result["status"],"PARTIAL_NOT_SEVEN_DAY_TOTAL")
        self.assertFalse(result["runtime"]["pdf_downloads"])
        self.assertEqual(result["runtime"]["d1_writes"],0)

if __name__=="__main__":
    unittest.main()
