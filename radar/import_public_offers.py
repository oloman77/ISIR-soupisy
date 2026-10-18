"""Idempotently import manually researched public *sale listings* into isolated Radar D1.

This is NOT an ISIR crawler and does not attest current availability.
Official CUZK cadastral name is checked before any DB write. Only new source
records are created. Existing private title/notes/status/history are untouched.
"""
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
import json
import re

from radar.import_legacy import TARGETS, normal, territories

SOURCE_FILE=Path(__file__).with_name("curated_offers.json")
ID_RX=re.compile(r"^[a-z0-9]{2,20}$")
PARCEL_RX=re.compile(r"^(?:st\.\s*)?\d+(?:/\d+)?$",re.I)

def validate(item, mapping, today=None):
    today=today or date.today()
    if set(item.keys()) != {
        "source","source_id","source_url","title","property_type",
        "district","municipality","cadastral_territory","parcels","lv",
        "area_m2","case_number","source_title","price_czk",
        "published_at","sale_end","checked_at","administrator",
        "sale_method","source_summary"}:
        raise ValueError("Unexpected or missing source field")
    if item["source"]!="portaldrazeb-insolvency" or not ID_RX.fullmatch(item["source_id"]):
        raise ValueError("Unexpected source ID")
    url=urlsplit(item["source_url"])
    if (url.scheme!="https" or url.netloc!="www.portaldrazeb.cz"
        or url.path!="/insolvencni-zamer/"+item["source_id"]
        or url.query or url.fragment):
        raise ValueError("Unsupported listing URL")
    if item["district"] not in TARGETS:
        raise ValueError("Outside the two approved districts")
    exact=mapping.get(normal(item["cadastral_territory"]),set())
    if exact != {(item["district"],item["municipality"])}:
        raise ValueError("Cadastral area not uniquely mapped to target district")
    if item["property_type"]!="Pozemek":
        raise ValueError("Only researched land listing is supported in this pilot")
    if (not isinstance(item["title"],str) or not 3<=len(item["title"])<=180
        or not isinstance(item["source_title"],str) or len(item["source_title"])>180
        or not isinstance(item["source_summary"],str) or not item["source_summary"]
        or len(item["source_summary"])>900):
        raise ValueError("Invalid length or description")
    if (not isinstance(item["parcels"],list) or not 1<=len(item["parcels"])<=15
        or not all(isinstance(p,str) and PARCEL_RX.fullmatch(p) for p in item["parcels"])):
        raise ValueError("Invalid parcel numbers")
    if (not str(item["lv"]).isdigit()
        or type(item["price_czk"]) is not int or not 0<item["price_czk"]<10**12
        or type(item["area_m2"]) is not int or not 0<item["area_m2"]<10**9):
        raise ValueError("Invalid size, price or LV")
    published=date.fromisoformat(item["published_at"])
    ends=date.fromisoformat(item["sale_end"])
    checked=date.fromisoformat(item["checked_at"])
    if not (published<=checked<=today<=ends):
        raise ValueError("Listing is old, not yet checked or expired; requires review")
    if not re.fullmatch(r"[A-Z]{3,6}\s+\d+\s+INS\s+\d+/\d{4}",item["case_number"]):
        raise ValueError("Missing full insolvency case reference")
    if item["sale_method"]!="Prodej mimo dražbu":
        raise ValueError("Incorrect sale method")
    return {
      "id":"sale:portaldrazeb:"+item["source_id"],
      "source_id":"sale:portaldrazeb:"+item["source_id"],
      "title":item["title"],
      "property_type":item["property_type"],
      "district":item["district"],"municipality":item["municipality"],
      "cadastral_territory":item["cadastral_territory"],
      "lv":item["lv"],"parcel":", ".join(item["parcels"]),
      "area_m2":item["area_m2"],"source_type":item["source"],
      "external_id":item["source_id"],"source_url":item["source_url"],
      "source_title":item["source_title"],"published_at":item["published_at"],
      "price_czk":item["price_czk"],"raw_excerpt":item["source_summary"],
    }


def build_statements(record):
    # INSERT-ONLY and deterministic IDs prevent overwriting private decisions
    # even if the workflow is manually re-run.
    return [
      ("INSERT INTO properties (id,title,property_type,district,municipality,"
       "cadastral_territory,lv,parcel,area_m2,location_confidence,sale_phase)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
       (record["id"],record["title"],record["property_type"],record["district"],
        record["municipality"],record["cadastral_territory"],record["lv"],
        record["parcel"],record["area_m2"],"suggested","listed")),
      ("INSERT INTO property_sources (id,property_id,source_type,external_id,"
       "source_title,source_url,published_at,price_czk,raw_excerpt)"
       " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
       (record["source_id"],record["id"],record["source_type"],
        record["external_id"],record["source_title"],record["source_url"],
        record["published_at"],record["price_czk"],record["raw_excerpt"])),
    ]


def run():
    data=json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
    if data.get("catalog_version")!=1 or not isinstance(data.get("items"),list):
        raise RuntimeError("Unsupported source file")
    if len(data["items"])!=1:
        raise RuntimeError("This pilot must contain exactly one curated listing")
    mapping=territories()
    records=[validate(item,mapping) for item in data["items"]]
    if len({r["id"] for r in records})!=len(records):
        raise RuntimeError("Duplicate listing IDs")

    # No connection to Cloudflare until ALL records pass source validation.
    from radar.initialize import resolve
    db=resolve()
    for r in records:
        for statement,params in build_statements(r):
            db.query(statement,params)
        found=db.query("SELECT p.id,p.district,s.source_url,s.price_czk "
                       "FROM properties p JOIN property_sources s ON s.property_id=p.id "
                       "WHERE p.id=? AND s.id=?",(r["id"],r["source_id"]))
        if (len(found)!=1 or found[0]["district"]!=r["district"]
            or found[0]["source_url"]!=r["source_url"]
            or found[0]["price_czk"]!=r["price_czk"]):
            raise RuntimeError("Import verification failed")
        print("VERIFIED INSERT-ONLY LISTING:",r["id"],r["district"],
              "source:",r["source_url"])
    print("Done. Source sale remains subject to availability check with administrator.")
    print("NO legacy crawler run, NO property_decisions updates, NO history updates.")

if __name__=="__main__":
    run()
