"""Read-only 30-document pilot: soupises of insolvent debtors' estate.

Old crawler and Cloudflare Radar/D1 are never imported or used.
This script selects candidates using *document metadata*, not asserted truth,
then probes official public PDF sources. Its output is an audit/triage result,
not proof of ownership, sale or membership in the estate.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
import io
import json
import re

from radar.import_legacy import ROOT, TARGETS, normal, territories

SOURCE=ROOT/"docs/results.json"
SELECT_SOUPIS=20
SELECT_CONTROL=10
MAX_PDF_BYTES=12_000_000
MAX_PDF_PAGES=45
MAX_OCR_TOTAL=8

# Only strong metadata indicators are counted as potential inventories.
# "Seznam přihlášených pohledávek" must not be accepted as an inventory.
SOUPIS=re.compile(
    r"(?:soupis.{0,55}majetkov.{0,24}podstat|"
    r"(?:dopln[eě]n[ií]|zm[eě]na|aktualizac[eí]).{0,65}soupis|"
    r"soupis\s+majetku)",
    re.I|re.S,
)
CONTROL=re.compile(
    r"(?:přihl[aá]šen.{0,25}pohled[aá]v|sd[eě]len[ií]|"
    r"n[aá]vrh|př[ií]loh|zpr[aá]va|pohled[aá]vk)",
    re.I,
)
INVENTORY_TEXT=re.compile(r"soupis.{0,50}majetkov.{0,30}podstat",re.I|re.S)
PARCEL=re.compile(
    r"\b(?:parc(?:ela|ely|elní|el\.|\.)|pozemek)\s*"
    r"(?:č(?:íslo|\.)?\s*)?(\d{1,6}(?:/\d{1,6})?)",re.I)
LV=re.compile(r"(?:list\s+vlastnictv[ií]|\bLV)\s*(?:č(?:íslo|\.)?\s*)?(\d{1,7})\b",re.I)
KU=re.compile(
    r"(?:katastr[aá]ln[ií]\s+[úu]zem[ií]|k\s*\.\s*[úu]\s*\.)"
    r"\s*[:\-]?\s*([A-Za-zÁ-ž0-9][A-Za-zÁ-ž0-9 \t'-]{2,99})",re.I)

def safe_pdf_url(value):
    z=urlsplit(str(value or ""))
    p=parse_qs(z.query,keep_blank_values=True)
    if not (z.scheme=="https" and z.hostname=="isir.justice.cz"
            and z.port in (443,8443)
            and z.path=="/isir_public_ws/doc/Document"
            and not z.username and not z.password and not z.fragment
            and set(p)=={"idDokument"} and len(p["idDokument"])==1
            and p["idDokument"][0].isdigit()):
        raise ValueError("Unexpected document URL")
    return value

def category(row):
    # Only titles/metadata: the stored "obsahuje_nemovitost" flag is NOT used
    # to assert that the PDF is an actual soupis.
    title=str(row.get("popis_udalosti") or "")
    typ=str(row.get("typ_udalosti") or "")
    combined=title+" "+typ
    if SOUPIS.search(combined):return "soupis_candidate"
    if CONTROL.search(combined):return "control_candidate"
    return ""

def stable_order(row):
    uid=str(row.get("id") or "")
    return sha256(("isir-soupis-pilot-1:"+uid).encode()).hexdigest()

def choose(source):
    source_rows=source.get("items") or []
    pools={"soupis_candidate":[],"control_candidate":[]}
    seen=set()
    counts=Counter()
    for row in source_rows:
        uid=str(row.get("id") or "")
        if not uid or uid in seen:continue
        seen.add(uid)
        counts["archive_rows"]+=1
        try:safe_pdf_url(row.get("dokument_url"))
        except (ValueError,TypeError):continue
        typ=category(row)
        if not typ:continue
        counts[typ+"_eligible"]+=1
        # Prioritize already flagged real estate candidates WITHOUT treating
        # those flags as evidence. The sample still spans different cases.
        pools[typ].append(row)
    def pick(pool,limit):
        pool.sort(key=lambda r:(
            not (r.get("obsahuje_nemovitost") is True),
            stable_order(r)))
        selected=[];used_cases=set()
        for row in pool:
            key=" ".join(str(row.get("spisova_znacka") or "").upper().split())
            if not key:key=str(row.get("id"))
            if key in used_cases:continue
            selected.append(row);used_cases.add(key)
            if len(selected)>=limit:break
        return selected
    chosen=pick(pools["soupis_candidate"],SELECT_SOUPIS)
    used={str(r["id"]) for r in chosen}
    controls=[r for r in pick(pools["control_candidate"],SELECT_CONTROL+SELECT_SOUPIS)
              if str(r["id"]) not in used][:SELECT_CONTROL]
    return [(x,"soupis_candidate") for x in chosen]+[
        (x,"control_candidate") for x in controls],dict(counts)

def canon(s):
    return re.sub(r"[^a-z0-9]+"," ",normal(s)).strip()

def cadastral_names(text,mapping):
    # A territory may be mentioned incidentally and is NOT necessarily an
    # estate asset. Exact CUZK lookup is a geographical hint only.
    index={canon(n):pairs for n,pairs in mapping.items()}
    found={}
    for m in KU.finditer(text):
        v=canon(m.group(1))
        toks=v.split()
        for leading in (toks,toks[1:] if toks and toks[0] in {"v","ve"} else []):
            for size in range(min(len(leading),9),0,-1):
                name=" ".join(leading[:size])
                if name in index:
                    found[name]=index[name]
                    break
            if any(" ".join(leading[:n]) in found for n in range(1,len(leading)+1)):
                break
    return found

def pdf_text_probe(row,mapping,ocr_budget):
    import subprocess
    import tempfile
    from pypdf import PdfReader
    item={"source_id":str(row["id"]),"status":"failed","ocr_pages":0}
    try:
        url=safe_pdf_url(row["dokument_url"])
        req=Request(url,headers={"User-Agent":"ISIR-Radar-Soupis-Pilot/1.0"})
        with urlopen(req,timeout=35) as response:
            if response.status!=200:raise ValueError("HTTP status not OK")
            if urlsplit(response.url).hostname!="isir.justice.cz":
                raise ValueError("Redirect to another host")
            data=response.read(MAX_PDF_BYTES+1)
        if len(data)>MAX_PDF_BYTES:raise ValueError("PDF exceeds size cap")
        if not data.startswith(b"%PDF"):raise ValueError("Not a PDF")
        reader=PdfReader(io.BytesIO(data),strict=False)
        total=len(reader.pages);processed=min(total,MAX_PDF_PAGES)
        alltext=[];pages_with_text=0
        need_ocr=[]
        for i in range(processed):
            text=reader.pages[i].extract_text() or ""
            if len(text.strip())>=80:pages_with_text+=1
            elif len(need_ocr)<2:need_ocr.append(i)
            alltext.append(text)
        # Targeted OCR only for pages with poor native text. Globally capped.
        if need_ocr and ocr_budget>0:
            with tempfile.TemporaryDirectory() as tmp:
                src=Path(tmp)/"doc.pdf";src.write_bytes(data)
                for i in need_ocr[:ocr_budget]:
                    prefix=str(Path(tmp)/("page"+str(i+1)))
                    try:
                        subprocess.run(["pdftoppm","-f",str(i+1),"-l",str(i+1),
                            "-singlefile","-r","130","-png",str(src),prefix],
                            timeout=30,check=True,capture_output=True)
                        out=subprocess.run(["tesseract",prefix+".png","stdout",
                            "-l","ces+eng"],timeout=50,check=True,capture_output=True)
                        decoded=out.stdout.decode("utf-8",errors="replace")
                        alltext[i]+="\n"+decoded
                        item["ocr_pages"]+=1
                    except (OSError,subprocess.TimeoutExpired,subprocess.CalledProcessError):
                        item["ocr_error_pages"]=item.get("ocr_error_pages",0)+1
        document="\n".join(alltext)
        names=cadastral_names(document,mapping)
        districts=sorted({district for pairs in names.values()
                          for district,municipality in pairs})
        targets=sorted(set(districts)&TARGETS)
        item.update({
          "status":"ok",
          "pdf_pages_total":total,
          "pdf_pages_examined":processed,
          "native_text_pages":pages_with_text,
          "pdf_inventory_phrase":bool(INVENTORY_TEXT.search(document)),
          "parcel_mentions":len(PARCEL.findall(document)),
          "lv_mentions":len(LV.findall(document)),
          "cadastral_names_count":len(names),
          "cadastral_names":sorted(names)[:10],
          "districts_mentioned":districts,
          "target_district_mentions":targets,
          "evidence_level":"UNVERIFIED_DOCUMENT_MENTION",
        })
    except Exception as exc:
        item["error_type"]=type(exc).__name__
    return item

def execute(source,mapping,scan=False):
    selected, counts=choose(source)
    budget=MAX_OCR_TOTAL
    out=[]
    for row,role in selected:
        record={
          "source_id":str(row["id"]),
          "category_from_metadata":role,
          "case_reference":str(row.get("spisova_znacka") or "")[:50],
          "original_real_estate_suspicion":row.get("obsahuje_nemovitost") is True,
          "public_pdf_url":row["dokument_url"],
          "human_review_status":"not_reviewed",
        }
        if scan:
            probe=pdf_text_probe(row,mapping,budget)
            record.update(probe)
            budget-=probe.get("ocr_pages",0)
        out.append(record)
    return {
      "archival_snapshot":source.get("updated_at"),
      "selection_counts":counts,
      "requested_soupis_candidates":SELECT_SOUPIS,
      "requested_controls":SELECT_CONTROL,
      "selected_soupis_candidates":sum(r["category_from_metadata"]=="soupis_candidate" for r in out),
      "selected_control_candidates":sum(r["category_from_metadata"]=="control_candidate" for r in out),
      "selected_total":len(out),
      "pdf_probing_enabled":scan,
      "pdf_probes_successful":sum(r.get("status")=="ok" for r in out),
      "pdf_inventory_phrases_found":sum(r.get("pdf_inventory_phrase",False) for r in out),
      "pdfs_with_any_cadastral_names":sum(bool(r.get("cadastral_names_count")) for r in out),
      "pdfs_with_target_district_mentions":sum(bool(r.get("target_district_mentions")) for r in out),
      "ocr_pages_attempted_and_succeeded":MAX_OCR_TOTAL-budget,
      "documents":out,
      "conclusions_are_manual_review_pending":True,
      "db_modified":False,
      "legacy_crawler_started":False,
      "notes":[
        "Soupis/control categories are inferred from ISIR event metadata; they are not manually verified.",
        "A mention of a property does not establish its inclusion in the debtor's estate.",
        "Cadastral names can be incidental references; no property is entered into Radar.",
        "Pages exceeding scan/OCR caps require selective follow-up."
      ]
    }

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--scan",action="store_true")
    p.add_argument("--output",type=Path,default=Path("soupis-pilot-result.json"))
    args=p.parse_args()
    source=json.loads(SOURCE.read_text(encoding="utf-8"))
    mapping=territories() if args.scan else {}
    outcome=execute(source,mapping,scan=args.scan)
    args.output.write_text(json.dumps(outcome,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # Logs contain no PDF text, person names, private Radar notes or credentials.
    public={k:v for k,v in outcome.items() if k not in {"documents","selection_counts"}}
    public["selection_counts"]=outcome["selection_counts"]
    print("READ-ONLY ISIR SOUPIS PILOT")
    print(json.dumps(public,ensure_ascii=False,indent=2))
    for r in outcome["documents"]:
        print("DOC",r["source_id"],r["category_from_metadata"],
              r.get("status","unscanned"),
              "inventory_phrase",r.get("pdf_inventory_phrase","n/a"),
              "districts",r.get("districts_mentioned",[]),
              "parcel_hits",r.get("parcel_mentions",0),
              "ocr",r.get("ocr_pages",0),
              "error",r.get("error_type","none"))

if __name__=="__main__":
    main()
