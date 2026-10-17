"""Radar diagnostic: read-only candidate counts and dedicated D1 schema initialization."""
import json
import os
import urllib.request

from d1_preflight import D1
from radar.import_legacy import ROOT, SCHEMA, candidates, territories

NAME = "isir-radar"


def resolve():
    account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token=os.environ["CLOUDFLARE_API_TOKEN"]
    request=urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database?name={NAME}",
        headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
    with urllib.request.urlopen(request, timeout=40) as r:
        data=json.load(r)
    if not data.get("success"):
        raise RuntimeError("D1 discovery not successful")
    matches=[d for d in data["result"] if d.get("name")==NAME and d.get("jurisdiction")=="eu"]
    if len(matches)!=1:
        raise RuntimeError("Radar D1 must be a single EU-jurisdiction DB")
    os.environ["CLOUDFLARE_D1_DATABASE_ID"]=matches[0]["uuid"]
    d1=D1()
    if d1.request().get("name")!=NAME:
        raise RuntimeError("D1 target name mismatch")
    return d1


def initialize(d1):
    sql=SCHEMA.read_text(encoding="utf-8")
    # schema.sql has no inline semicolon-delimited triggers
    for statement in sql.split(";"):
        statement="\n".join(line for line in statement.splitlines()
                            if not line.strip().startswith("--")).strip()
        if statement:
            d1.query(statement)
    result=d1.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'propert%'")
    names={row["name"] for row in result}
    if not {"properties","property_sources","property_decisions"}.issubset(names):
        raise RuntimeError("Schema validation failed")
    print("ISIR Radar D1 SQL schema installed and verified, no crawler change.")


def summarize():
    data=json.loads((ROOT/"docs/results.json").read_text(encoding="utf-8"))
    rows=data.get("items",[])
    if not isinstance(rows,list):
        raise RuntimeError("Legacy results invalid")
    confirmed=[r for r in rows if r.get("obsahuje_nemovitost") is True and
               r.get("pdf_status")=="ok" and bool(r.get("dokument_url"))]
    print(f"Legacy rows: {len(rows)}; PDF property candidates: {len(confirmed)}")
    print("Candidate with KU:",sum(bool(r.get("katastralni_uzemi")) for r in confirmed))
    if not confirmed:
        print("No confirmed candidates for Radar import")
        return
    mapping=territories()
    selected=list(candidates(data,mapping))
    district_counts={}
    for _,(district,_,_) in selected:
        key=district or "Neurčeno"
        district_counts[key]=district_counts.get(key,0)+1
    print("Geographically selected provisional records:",len(selected))
    print("District breakdown:",json.dumps(district_counts,ensure_ascii=False))
    print("No documents, personal notes or names are logged.")


if __name__=="__main__":
    initialize(resolve())
    summarize()
