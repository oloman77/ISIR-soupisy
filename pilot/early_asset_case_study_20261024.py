"""One-off read-only historical sample, NOT a crawler.

Selects up to 9 public ISIR PDFs via frozen 2026-09-17 archive metadata:
  3 early documents possibly associated with a later soupis,
  3 unmatched early documents, up to 3 later soupis documents.
No OCR, no D1, no edits, no bulk network walk. Full court prefix often
absent in legacy spis, so alleged pairs are *hypotheses*, not verified cases.
"""
import io,json,re,hashlib,collections
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from datetime import datetime,timezone
from pypdf import PdfReader
from pilot.soupis_documents import safe_pdf_url

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/"docs/results.json"
LIMIT=9
MAX_BYTES=8_000_000
MAX_PAGES=25
RX_EARLY=re.compile(r"insolven[čc]n[ií]\s+n[aá]vrh|n[aá]vrh\s+na\s+povolen[ií]\s+oddlu[žz]en[ií]|seznam\s+majetku|p[řr][ií]loh[ay]",re.I)
RX_SOUPIS=re.compile(r"soupis.{0,50}majetkov.{0,30}podstat",re.I)
RX_PARCEL=re.compile(r"\bparc(?:ela|ely|\.|elní)\s*(?:[čc]\.?|[čc][ií]slo)?\s*\d{1,6}(?:/\d{1,6})?\b",re.I)
RX_KU=re.compile(r"katastr[aá]ln(?:[ií]|[ií]m|[ií]ho)\s+[úu]zem[ií]",re.I)
RX_LV=re.compile(r"\b(?:LV\s*[čc]?\.?\s*\d+|list\s+vlastnictv[ií]\s*[čc]?\.?\s*\d+)\b",re.I)
RX_LIST=re.compile(r"seznam\s+majetku|v[eě]ci\s+nemovit[eé]|nemovit[ýéy]\s+majetek",re.I)

def timestamp(row):
    value=row.get("datum_zverejneni") or row.get("datum_zalozeni")
    try:return datetime.fromisoformat(value.replace("Z","+00:00"))
    except (ValueError,AttributeError):return None

def key(row):
    return " ".join(str(row.get("spisova_znacka") or "").upper().split())

def choose(rows):
    by=collections.defaultdict(list)
    for row in rows:
        k=key(row)
        if not k or not timestamp(row):continue
        try:safe_pdf_url(row.get("dokument_url"))
        except (ValueError,TypeError):continue
        by[k].append(row)
    pairs=[];unpaired=[]
    for k,values in by.items():
        early=sorted((r for r in values if RX_EARLY.search(str(r.get("popis_udalosti") or ""))
                      and not RX_SOUPIS.search(str(r.get("popis_udalosti") or ""))),key=timestamp)
        soup=sorted((r for r in values if RX_SOUPIS.search(str(r.get("popis_udalosti") or ""))),key=timestamp)
        if early and soup and timestamp(early[0])<timestamp(soup[-1]):
            for e in early:
                later=[s for s in soup if timestamp(s)>timestamp(e)]
                if later:
                    pairs.append((e,later[0]))
                    break
        if early and not soup:unpaired.append(early[0])
    stable=lambda r:hashlib.sha256(str(r["id"]).encode()).hexdigest()
    pairs.sort(key=lambda p:stable(p[0]))
    unpaired.sort(key=stable)
    chosen=[];ids=set()
    for a,b in pairs[:3]:
        for r,kind in [(a,"early_with_same_abbreviated_spis"),(b,"later_soupis_with_same_abbreviated_spis")]:
            if len(chosen)>=LIMIT:break
            if str(r["id"]) not in ids:
                ids.add(str(r["id"]));chosen.append((r,kind))
    for r in unpaired:
        if len(chosen)>=LIMIT:break
        if str(r["id"]) not in ids:ids.add(str(r["id"]));chosen.append((r,"early_no_soupis_in_archive"))
    # If few pairs, fill with other early types and independent soupises.
    others=[r for values in by.values() for r in values if (
        RX_EARLY.search(str(r.get("popis_udalosti") or "")) or
        RX_SOUPIS.search(str(r.get("popis_udalosti") or "")))]
    others.sort(key=stable)
    for r in others:
        if len(chosen)>=LIMIT:break
        if str(r["id"]) not in ids:ids.add(str(r["id"]));chosen.append((r,"fallback_archive"))
    return chosen,{"abbreviated_case_keys":len(by),
       "potential_early_to_soupis_pairs":len(pairs),
       "early_without_soupis_archive":len(unpaired),
       "candidate_case_pairs_tentative":True}

def inspect(r,kind):
    item={"source_id":str(r["id"]),"role":kind,
          "event_desc":str(r.get("popis_udalosti") or "")[:95],
          "published_at":str(r.get("datum_zverejneni") or ""),
          "case_key_sha256_prefix":hashlib.sha256(key(r).encode()).hexdigest()[:16],
          "pdf_url":r.get("dokument_url"),"status":"failed"}
    try:
        u=safe_pdf_url(r.get("dokument_url"))
        with urlopen(Request(u,headers={"User-Agent":"ISIR-Radar-One-Time-Early-Asset-Study/1.0"}),timeout=22) as h:
            if h.status!=200 or "isir.justice.cz"!=h.url.split("/")[2].split(":")[0]:
                raise ValueError("redirect/status")
            b=h.read(MAX_BYTES+1)
        if len(b)>MAX_BYTES:raise ValueError("above_8mb_limit")
        if not b.startswith(b"%PDF"):raise ValueError("no_pdf_content")
        pdf=PdfReader(io.BytesIO(b),strict=False)
        pcount=len(pdf.pages)
        textpages=0;hits=collections.Counter()
        for p in pdf.pages[:MAX_PAGES]:
            t=p.extract_text() or ""
            if len(t.strip())>80:textpages+=1
            for label,rx in [("list_text",RX_LIST),("parcel",RX_PARCEL),
                ("katastralni_uzemi",RX_KU),("lv",RX_LV)]:
                if rx.search(t):hits[label]+=1
        item.update(status="ok",bytes=len(b),pages=pcount,
                    inspected_pages=min(pcount,MAX_PAGES),
                    pages_with_extractable_text=textpages,
                    pages_with_terms=dict(hits),
                    estate_asset_proven=False)
    except Exception as exc:
        item["error_type"]=type(exc).__name__
        if isinstance(exc,ValueError):item["error_detail"]=str(exc)[:70]
    return item

def main():
    data=json.loads(ARCHIVE.read_text(encoding="utf-8"))
    sample,metadata=choose(data["items"])
    out={"snapshot":data.get("updated_at"),
      "selected_documents":len(sample),"selection":metadata,
      "results":[inspect(r,kind) for r,kind in sample],
      "read_only":True,"pdf_download_cap":LIMIT,"ocr":False,
      "old_crawler_started":False,"production_writes":0,
      "limitations":[
        "Historical selection lacks verified full court-and-case identity.",
        "Only limited first 25 PDF pages inspected; no OCR.",
        "Source documents may be appendices without actual property inventory.",
        "No supported matched pair means lead-time not measurable, not zero.",
        "No person or actual parcel identifiers printed."]
      }
    from collections import Counter
    out["status_counts"]=dict(Counter(x["status"] for x in out["results"]))
    print("EARLY_DOC_EXPERIMENT_JSON")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    Path("early-doc-experiment.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
