"""Seven-day ISIR WS_1 metadata feasibility audit, strictly read-only.

This is a BOUNDED live API pilot, NOT a full historical backfill. Official
WS_1 returns at most 1000 sequential actions per ID request and has no
published calendar-date filter. The official manual recommends at least
ten minutes between calls by one consumer. Fail closed on incomplete range:
NEVER label a small sample as a full 7-day measurement.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET
import json
import re
import time
import unicodedata

SERVICE="https://isir.justice.cz:8443/isir_public_ws/IsirWsPublicService"
CATALOG="https://isir.justice.cz/isir/help/Cis_udalosti.xls"
MAX_CALLS=2
MIN_SOAP_INTERVAL_SECONDS=600
SAMPLE_ID_LOOKBACK=800
MAX_SOAP_BYTES=24_000_000
TIMEOUT=65
OUT=Path("isir-metadata-7d-report.json")

def local(tag):
    return tag.rsplit("}",1)[-1]

def child_text(element,key):
    for child in element:
        if local(child.tag)==key:
            return (child.text or "").strip()
    return ""

def dt(value):
    if not value:return None
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError,OverflowError):
        return None

def normalize(text):
    s=unicodedata.normalize("NFKD",str(text or "").casefold())
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def classify(popis):
    """Lexical candidates only; official numeric-code mapping is separate."""
    t=normalize(popis)
    if re.search(r"(?:oprava|opraveni|opraveny|zmena|zmeny|uprava|upraveny)",t) and re.search(r"soupis",t):
        return "oprava_zmena_soupisu"
    if re.search(r"(?:doplneni|doplnujici|dodatek|aktualizace|aktualizovany|rozsireni)",t) and re.search(r"soupis",t):
        return "doplneni_soupisu"
    if re.search(r"soupis.{0,60}majetkov.{0,25}podstat|soupis\s+majetku",t):
        if re.search(r"(?:vyzva|navrh|pripomink|namitk|zadam|vyrozumeni|k\s+soupisu|o\s+soupisu)",t):
            return "nejednoznacny_soupis"
        return "puvodni_soupis_kandidat"
    if re.search(r"(?:zpen[eě]z|drazb|prodej|pokyn.{0,40}zpen|souhlas.{0,40}prodej|zprava.{0,50}majetk|oceneni\s+majetk)",t):
        return "dalsi_majetkove_udalosti"
    if re.search(r"(?:zprava\s+(?:insolvencniho\s+)?spravce|majetkov|nemovitost|soupis)",t):
        return "nejednoznacny_majetkovy_dokument"
    return "ostatni"

def soap_payload(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
      '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
      'xmlns:typ="http://isirpublicws.cca.cz/types/">'
      '<soapenv:Header/><soapenv:Body>'+body+'</soapenv:Body></soapenv:Envelope>').encode()

def soap_request(body):
    request=Request(SERVICE,data=soap_payload(body),
       headers={"Content-Type":"text/xml; charset=utf-8","SOAPAction":'""',
                "User-Agent":"ISIR-Radar-7day-Metadata-Pilot/1.0"},method="POST")
    with urlopen(request,timeout=TIMEOUT) as response:
        if response.status!=200: raise RuntimeError("non200")
        if response.url!=SERVICE:raise RuntimeError("unexpected_redirect")
        raw=response.read(MAX_SOAP_BYTES+1)
        if len(raw)>MAX_SOAP_BYTES:raise RuntimeError("response_size_cap")
    root=ET.fromstring(raw)
    faults=[e for e in root.iter() if local(e.tag)=="Fault"]
    if faults:raise RuntimeError("soap_fault")
    return root,len(raw)

def official_catalog():
    """GET only official XLS; failure is explicit, never invent numeric codes."""
    result={"source_url":CATALOG,"loaded":False,"verified_code_entries":0}
    try:
        req=Request(CATALOG,headers={"User-Agent":"ISIR-Radar-7day-Metadata-Pilot/1.0"})
        with urlopen(req,timeout=30) as resp:
            if resp.status!=200 or resp.url!=CATALOG:raise ValueError("bad_status_or_redirect")
            data=resp.read(6_000_001)
        if len(data)>6_000_000:raise ValueError("catalog_too_large")
        if not data.startswith(b"\xd0\xcf\x11\xe0"):
            raise ValueError("catalog_not_ole_xls")
        import xlrd
        book=xlrd.open_workbook(file_contents=data)
        result["loaded"]=True
        result["sheets"]=[{"name":sh.name,"rows":sh.nrows,"cols":sh.ncols}
                          for sh in book.sheets()]
        # Heuristic extraction only for sheet identification: official
        # mapping must be manually checked against column headings.
        entries={}
        for sh in book.sheets():
            for r in range(min(sh.nrows,10000)):
                values=[str(sh.cell_value(r,c)).strip() for c in range(min(sh.ncols,9))]
                for c in range(min(len(values)-1,3)):
                    code=values[c]
                    if re.fullmatch(r"\d+(?:\.0)?",code) and values[c+1] and not values[c+1].isdigit():
                        k=str(int(float(code)))
                        entries.setdefault(k,set()).add(values[c+1][:170])
                        break
        result["candidate_entries"]=sum(len(v) for v in entries.values())
        result["candidate_code_sample"]={k:sorted(v)[:2] for k,v in list(entries.items())[:15]}
        return result,entries
    except Exception as exc:
        result["error_type"]=type(exc).__name__
        result["error_reason"]=str(exc)[:80] if isinstance(exc,ValueError) else None
        return result,{}

def parse_actions(root):
    rows=[]
    for el in root.iter():
        if local(el.tag)!="data":continue
        rid=child_text(el,"id")
        if not rid.isdigit():continue
        date=child_text(el,"datumZverejneniUdalosti")
        note=child_text(el,"poznamka")
        # Notes can contain personal data. Extract only Boolean flags and
        # NEVER retain or print note contents or personally identifying fields.
        flag_secondary=""
        if note:
            try:
                nroot=ET.fromstring(note)
                for child in nroot.iter():
                    if local(child.tag)=="priznakAnVedlejsiDokument":
                        flag_secondary=(child.text or "").strip()
                        break
            except ET.ParseError:pass
        rows.append({
            "id":int(rid),
            "published":date,
            "type":child_text(el,"typUdalosti"),
            "description":child_text(el,"popisUdalosti")[:250],
            "document_url":child_text(el,"dokumentUrl"),
            "secondary_document_flag":flag_secondary,
            "section":child_text(el,"oddil"),
            # Year alone helps demonstrate monitoring of older proceedings,
            # without storing case/person identifiers.
            "case_year":(re.search(r"\bINS\s+\d+[/ ]+(\d{4})\b",child_text(el,"spisovaZnacka")) or [None,None])[1]
        })
    rows.sort(key=lambda r:r["id"])
    return rows

def analyze(rows,start,end,catalog,lookup,batch_meta):
    inwin=[]
    older=[]
    future=[]
    bad_date=0
    by_code=Counter(); by_pair=Counter(); by_group=Counter()
    docs_by_group=defaultdict(set)
    codes=defaultdict(lambda:{"count":0,"descriptions":Counter(),"classifications":Counter()})
    missing_doc=0
    for r in rows:
        published=dt(r["published"])
        if published is None:
            bad_date+=1
            continue
        if published<start:older.append(r);continue
        if published>end:future.append(r);continue
        inwin.append(r)
        typ=r["type"] or "(missing)"
        desc=r["description"] or "(missing)"
        group=classify(desc)
        by_code[typ]+=1;by_pair[(typ,desc)]+=1;by_group[group]+=1
        codes[typ]["count"]+=1
        codes[typ]["descriptions"][desc]+=1
        codes[typ]["classifications"][group]+=1
        if not r["document_url"]:
            missing_doc+=1
        else:
            docs_by_group[group].add(r["document_url"])
    event_codes=[]
    for code,e in sorted(codes.items(),key=lambda x:-x[1]["count"]):
        mapped=lookup.get(code,set())
        observed=set(e["descriptions"])
        event_codes.append({
          "code":code,"count":e["count"],
          "observed_descriptions":dict(e["descriptions"].most_common(8)),
          "classes":dict(e["classifications"]),
          "official_catalog_candidates":sorted(mapped)[:5],
          "official_code_verified":bool(catalog["loaded"] and mapped and
             any(normalize(a).strip()==normalize(b).strip()
                 for a in mapped for b in observed)),
          "conflict_multiple_descriptions":len(observed)>1
        })
    all_docs={r["document_url"] for r in inwin if r["document_url"]}
    all_ids=[r["id"] for r in rows]
    time_values=[dt(r["published"]) for r in rows if dt(r["published"])]
    id_diffs=[b-a for a,b in zip(all_ids,all_ids[1:])]
    # Even full 1000-row batch cannot prove seven-day completeness on its own.
    earliest=min(time_values).isoformat() if time_values else None
    latest=max(time_values).isoformat() if time_values else None
    fully_covers_start=bool(time_values and min(time_values)<=start)
    fully_covers_end=bool(time_values and max(time_values)>=end-timedelta(minutes=20))
    no_truncation=(len(rows)<1000 and max(all_ids,default=-1)>=batch_meta["id_at_initial_probe"])
    complete=(fully_covers_start and fully_covers_end and no_truncation
              and bad_date==0 and batch_meta.get("transport_ok",False))
    return {
      "status":"full_seven_days" if complete else "PARTIAL_NOT_SEVEN_DAY_TOTAL",
      "window_start_utc":start.isoformat(),"window_end_utc":end.isoformat(),
      "completeness":{
        "seven_day_coverage_verified":complete,
        "covers_start":fully_covers_start,
        "covers_end_with_20min_grace":fully_covers_end,
        "batch_below_1000_and_reached_initial_tip":no_truncation,
        "earliest_event_utc":earliest,"latest_event_utc":latest,
        "id_gaps_are_not_automatically_missing_records":True,
        "id_jump_count":sum(i>1 for i in id_diffs),
        "invalid_dates":bad_date,
        "older_than_window":len(older),"later_than_snapshot":len(future)
      },
      "observed_sample_not_week_total":{
        "actions_from_api":len(rows),
        "actions_with_valid_publication_in_window":len(inwin),
        "unique_document_urls":len(all_docs),
        "events_without_document_url":missing_doc,
        "old_case_year_events":sum(
            str(r["case_year"] or "").isdigit() and
            int(r["case_year"])<start.year for r in inwin),
        "categories":dict(by_group),
        "unique_docs_by_category":{k:len(v) for k,v in docs_by_group.items()},
        "ambiguous_categories_count":sum(v for k,v in by_group.items() if k.startswith("nejednoznacny")),
        "distinct_codes":len(by_code),
        "distinct_code_description_pairs":len(by_pair)
      },
      "codes":event_codes,
      "grouped_pairs":[{"code":c,"description":d,"count":n,
                        "lexical_category":classify(d)}
                       for (c,d),n in by_pair.most_common()],
      "estimated_seven_day_pdf_count":None if not complete else len(all_docs),
      "conservative_unconfirmed":"No manual PDF validation; lexical classes are candidates only."
    }

def execute(clock=None,wait=time.sleep, transport=soap_request,catalog_fetch=official_catalog):
    started=clock or datetime.now(timezone.utc)
    start=started-timedelta(days=7)
    catalog,entries=catalog_fetch()
    call_meta=[]
    times=[]
    def call(body):
        now=time.monotonic()
        if times:
            delta=now-times[-1]
            if delta<MIN_SOAP_INTERVAL_SECONDS:
                wait(MIN_SOAP_INTERVAL_SECONDS-delta+1)
        times.append(time.monotonic())
        root,size=transport(body)
        call_meta.append({"response_bytes":size,"successful":True})
        return root
    latest=call("<typ:getIsirWsPublicPosledniIdDataRequest/>")
    tip_values=[(e.text or "").strip() for e in latest.iter()
                if local(e.tag)=="cisloPosledniId"]
    if len(tip_values)!=1 or not tip_values[0].isdigit():
        raise RuntimeError("Cannot read latest ISIR action ID")
    tip=int(tip_values[0])
    # Under 1000 action IDs, strictly one batch. No scanning older cases.
    startid=max(0,tip-SAMPLE_ID_LOOKBACK)
    actions_root=call("<typ:getIsirWsPublicIdDataRequest><idPodnetu>"
                      +str(startid)+"</idPodnetu></typ:getIsirWsPublicIdDataRequest>")
    records=parse_actions(actions_root)
    unique={r["id"] for r in records}
    report=analyze(records,start,started,catalog,entries,
                   {"id_at_initial_probe":tip,"transport_ok":True})
    report["request_limits"]={
        "actual_soap_requests":len(call_meta),"soap_request_cap":MAX_CALLS,
        "minimum_interval_seconds":MIN_SOAP_INTERVAL_SECONDS,
        "latest_id_probe":tip,
        "requested_after_id":startid,
        "id_lookback":SAMPLE_ID_LOOKBACK,
        "returned_actions":len(records),
        "duplicate_action_ids":len(records)-len(unique),
        "all_calls_successful":len(call_meta)==2,
        "catalog_request":"one bounded GET; status separately reported"
    }
    report["catalog"]=catalog
    report["runtime"]={
      "finished_at_utc":datetime.now(timezone.utc).isoformat(),
      "old_crawler_started":False,"pdf_downloads":0,"d1_writes":0,
      "production_changes":0,
    }
    return report

def main():
    report={
      "status":"no_valid_live_measurement",
      "runtime":{"old_crawler_started":False,"pdf_downloads":0,
                 "d1_writes":0,"production_changes":0}
    }
    try:
        report=execute()
    except (HTTPError,URLError,TimeoutError,RuntimeError,ET.ParseError,ValueError) as exc:
        report["error_type"]=type(exc).__name__
        report["error_code"]=getattr(exc,"code",None)
        report["error_explanation"]="Live service error; counts and completeness NOT measured."
    finally:
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("ISIR WS1 READ-ONLY METADATA PILOT STATUS",report["status"])
        print(json.dumps({k:v for k,v in report.items() if k not in ("codes","grouped_pairs")},
                         ensure_ascii=False,indent=2))
        for r in report.get("codes",[]):
            if r["classes"].get("puvodni_soupis_kandidat") or r["classes"].get("doplneni_soupisu") or r["classes"].get("oprava_zmena_soupisu") or r["classes"].get("nejednoznacny_soupis"):
                print("SOUPIS_CODE",r["code"],"count",r["count"],
                      "catalog_verified",r["official_code_verified"],
                      "descriptions",list(r["observed_descriptions"].items())[:3])
    if report["status"]=="no_valid_live_measurement":
        raise SystemExit("No valid live sample; report saved with explicit error.")

if __name__=="__main__":
    main()
