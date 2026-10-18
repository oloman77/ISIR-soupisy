"""Targeted read-only audit of 6 PDFs with mapped cadastral units + 3 failures.

No D1, no old crawler, no ISIR bulk scan, no private annotations. Public official
PDFs are probed one by one with fixed size/page/OCR limits. Never claim that an
identified parcel belongs to the debtor's estate without human review.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import io
import json
import re
import subprocess
import tempfile

from radar.import_legacy import ROOT, TARGETS, territories
from pilot.soupis_documents import (
    INVENTORY_TEXT, LV, PARCEL, SOURCE, cadastral_names, safe_pdf_url
)

SIX = (80188662,80293338,79558955,80145767,79747190,79492073)
FAILED = (79893233,80244961,80027763)
IDS = SIX + FAILED
MAX_BYTES = 25_000_000
MAX_PAGES = 45
OCR_PAGES_EACH = 2
RENDER_DPI = 125

def identify_rows(source):
    lookup = {int(r["id"]):r for r in source["items"] if str(r.get("id","")).isdigit()}
    missing = set(IDS) - set(lookup)
    if missing:
        raise RuntimeError("Missing selected archived source IDs")
    return [lookup[i] for i in IDS]

def fetch_pdf(row):
    """Return bytes and coarse transport info; fail with an explicit error code."""
    url=safe_pdf_url(row.get("dokument_url"))
    request=Request(url,headers={"User-Agent":"ISIR-Radar-PDF-Review/1.0"})
    try:
        with urlopen(request,timeout=35) as resp:
            actual=urlsplit(resp.url)
            if actual.hostname!="isir.justice.cz" or actual.scheme!="https":
                return None,{"error_code":"unexpected_redirect"}
            reported=resp.headers.get("Content-Length")
            if reported and reported.isdigit() and int(reported)>MAX_BYTES:
                return None,{"error_code":"too_large_reported",
                             "reported_bytes":int(reported)}
            payload=resp.read(MAX_BYTES+1)
            if len(payload)>MAX_BYTES:
                return None,{"error_code":"too_large_streamed",
                             "limit_bytes":MAX_BYTES}
            if not payload.startswith(b"%PDF"):
                return None,{"error_code":"not_pdf","returned_bytes":len(payload),
                             "content_type":resp.headers.get("Content-Type","")[:80]}
            return payload,{"downloaded_bytes":len(payload)}
    except HTTPError as exc:
        return None,{"error_code":"http_error","http_status":exc.code}
    except (URLError,TimeoutError,OSError):
        return None,{"error_code":"network_error"}

def ocr_page(pdf_bytes, page_index):
    with tempfile.TemporaryDirectory() as tmp:
        doc=Path(tmp)/"source.pdf";doc.write_bytes(pdf_bytes)
        destination=str(Path(tmp)/"p")
        subprocess.run(["pdftoppm","-f",str(page_index+1),"-l",str(page_index+1),
            "-singlefile","-r",str(RENDER_DPI),"-png",str(doc),destination],
            check=True,capture_output=True,timeout=40)
        res=subprocess.run(["tesseract",destination+".png","stdout",
            "-l","ces+eng"],check=True,capture_output=True,timeout=60)
        return res.stdout.decode("utf-8","replace")

def page_evidence(text, page_number, mapping):
    names=cadastral_names(text,mapping)
    parcel=sorted(set(PARCEL.findall(text)))[:20]
    lv=sorted(set(LV.findall(text)))[:12]
    district=sorted({d for pairs in names.values() for d,m in pairs})
    return {
        "page":page_number,
        "inventory_phrase":bool(INVENTORY_TEXT.search(text)),
        "cadastral_names":sorted(names)[:15],
        "district_mentions":district,
        "parcels_mentioned":parcel,
        "lv_mentioned":lv,
        # Co-presence on a page is merely a hint, never confirmed ownership.
        "ku_and_parcel_same_page":bool(names and parcel)
    }

def inspect(row,mapping,include_ocr):
    base={
        "source_id":row["id"],
        "case_reference":str(row.get("spisova_znacka") or "")[:60],
        "metadata_event_type":str(row.get("popis_udalosti") or "")[:110],
        "document_url":safe_pdf_url(row.get("dokument_url")),
        "original_pdf_status":row.get("pdf_status"),
        "previous_audit":("had_cadastral_result" if int(row["id"]) in SIX
                          else "previous_ValueError"),
        "original_cadastral_names":(row.get("katastralni_uzemi") or [])[:10],
    }
    pdf, meta=fetch_pdf(row)
    base.update(meta)
    if pdf is None:
        base["analysis_status"]="download_failed"
        return base
    try:
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(pdf),strict=False)
        if reader.is_encrypted:
            base["analysis_status"]="encrypted_pdf"
            return base
        total_pages=len(reader.pages)
        pages=min(total_pages,MAX_PAGES)
        native_text={}
        extraction_errors=0
        for i in range(pages):
            try:native_text[i]=reader.pages[i].extract_text() or ""
            except Exception:
                native_text[i]=""
                extraction_errors+=1
        native_text_page_count=sum(len(t.strip())>=80 for t in native_text.values())
        # In the 6 interesting PDFs, try OCR only for the first two
        # genuinely blank pages. The other three focus on failure diagnosis.
        attempted=0
        succeeded=0
        if include_ocr:
            for i,t in native_text.items():
                if len(t.strip())>=80:continue
                if attempted>=OCR_PAGES_EACH:break
                attempted+=1
                try:
                    native_text[i]+="\n"+ocr_page(pdf,i)
                    succeeded+=1
                except (OSError,subprocess.TimeoutExpired,subprocess.CalledProcessError):
                    pass
        evidence=[page_evidence(text,i+1,mapping) for i,text in native_text.items()]
        interesting=[x for x in evidence if x["inventory_phrase"] or
                     x["cadastral_names"] or x["parcels_mentioned"] or x["lv_mentioned"]]
        found_districts=sorted({d for row in evidence for d in row["district_mentions"]})
        cadastral_pages=[x for x in evidence if x["cadastral_names"]]
        base.update({
            "analysis_status":"ok",
            "pdf_page_count":total_pages,
            "pages_inspected":pages,
            "pages_without_native_text":pages-native_text_page_count,
            "native_text_page_count":native_text_page_count,
            "native_extract_error_count":extraction_errors,
            "ocr_attempted":attempted,"ocr_succeeded":succeeded,
            "inventory_phrase_pages":[x["page"] for x in evidence if x["inventory_phrase"]],
            "cadastral_mention_pages":[x["page"] for x in cadastral_pages],
            "related_page_evidence":interesting[:25],
            "all_cadastral_district_mentions":found_districts,
            "target_district_mentions":sorted(set(found_districts)&TARGETS),
            "same_page_ku_parcel_count":sum(x["ku_and_parcel_same_page"] for x in evidence),
            "asset_in_estate_confirmed":False,
            "source_review_complete":False,
            "partial_document_review":total_pages>MAX_PAGES
        })
    except Exception as exc:
        base.update(analysis_status="pdf_parse_failure",error_code=type(exc).__name__)
    return base

def execute(source,mapping):
    rows=identify_rows(source)
    output=[inspect(row,mapping,int(row["id"]) in SIX) for row in rows]
    return {
      "snapshot_updated_at":source.get("updated_at"),
      "review_utc":datetime.now(timezone.utc).isoformat(),
      "scope":"Six previously location-positive documents plus three PDF failures",
      "documents":output,
      "count":len(output),
      "successful":sum(x["analysis_status"]=="ok" for x in output),
      "still_failed":sum(x["analysis_status"]!="ok" for x in output),
      "failure_reasons":dict(Counter(x.get("error_code","unknown") for x in output
          if x["analysis_status"]!="ok")),
      "target_district_mentions":sum(bool(x.get("target_district_mentions")) for x in output),
      "pages_with_cadastral_evidence":sum(len(x.get("cadastral_mention_pages",[])) for x in output),
      "pages_with_both_ku_and_parcel":sum(x.get("same_page_ku_parcel_count",0) for x in output),
      "ocr_pages_succeeded":sum(x.get("ocr_succeeded",0) for x in output),
      "no_ownership_inferences":True,
      "no_crawler":True,
      "no_database_writes":True,
    }

def main():
    source=json.loads(SOURCE.read_text(encoding="utf-8"))
    mapping=territories()
    output=execute(source,mapping)
    Path("soupis-6-plus-3-review.json").write_text(
        json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("READ-ONLY SOUPIS REVIEW: SIX POSITIVE PDFS + THREE FAILURES")
    public={k:v for k,v in output.items() if k!="documents"}
    print(json.dumps(public,ensure_ascii=False,indent=2))
    for row in output["documents"]:
        print("DOC",row["source_id"],row["previous_audit"],row["analysis_status"],
              "error",row.get("error_code","none"),"bytes",row.get("downloaded_bytes",
              row.get("reported_bytes","unknown")),"pages",row.get("pages_inspected",0),
              "inventory",row.get("inventory_phrase_pages",[]),
              "cadastral",row.get("cadastral_mention_pages",[]),
              "districts",row.get("all_cadastral_district_mentions",[]),
              "combined_pages",row.get("same_page_ku_parcel_count",0))
    print("Evidence is tentative. No private source text or user notes logged.")

if __name__=="__main__":
    main()
