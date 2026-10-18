"""Bounded read-only locality pilot for historic ISIR PDF candidates.

Uses the existing 2026-09-17 archive; does not start crawler, mutate D1,
touch personal decisions or ingest new records into Radar. IMPORTANT:
spisova_znacka in legacy data can lack court information. An exact match
is merely a possible link, NOT proof of an identical insolvency case.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import io
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from radar.import_legacy import ROOT, TARGETS, candidates, inferred_location, normal, territories

CASE_LIMIT = 30
PDF_LIMIT = 12
MAX_BYTES_PER_PDF = 6_000_000
MAX_PAGES_PER_PDF = 12

REG_KU = re.compile(
    r"(?:katastr[aá]ln[ií]\s+[úu]zem[ií]|k\s*\.\s*[úu]\s*\.)"
    r"\s*[:\-]?\s*([A-Za-zÁ-ž0-9][A-Za-zÁ-ž0-9 \t'-]{2,74})", re.I)
REG_PARCEL = re.compile(r"\bparc(?:ela|ely|elní|\.)?\s*(?:č\.?|číslo)?\s*\d+(?:/\d+)?\b", re.I)
REG_LV = re.compile(r"\b(?:list\s+vlastnictv[ií]|LV)\s*(?:č\.?|číslo)?\s*\d+\b", re.I)
REG_SALE = re.compile(
    r"\b(?:dražb[aáěy]|dražebn[ií]|zpen[eě]ž(?:en[ií]|ov[aá]n[ií])|"
    r"prodej(?:e|em|i)?|kupn[ií]\s+cena|vyvol[aá]vac[ií]\s+cena)\b", re.I)
REG_DOC_PRIORITY = re.compile(
    r"soupis|dražb|zpen[eě]ž|prodej|nab[ií]dk|kupn[ií]|nemovit|př[ií]loh|sd[eě]len[ií]",
    re.I)
REG_CASE = re.compile(r"^(?:[A-Z]{2,6}\s+\d+\s+)?INS\s+\d+\s*/\s*\d{4}$", re.I)


def case_key(row):
    # This may omit the court/case number prefix. All matches are tentative.
    key = " ".join(str(row.get("spisova_znacka") or "").upper().split())
    return key if REG_CASE.fullmatch(key) else ""


def unique_by_id(rows):
    used = set()
    out = []
    for row in rows:
        uid = str(row.get("id") or "")
        if uid and uid not in used:
            used.add(uid)
            out.append(row)
    return out


def make_cases(source, mapping):
    all_rows = source.get("items", [])
    by_key = defaultdict(list)
    for row in all_rows:
        key = case_key(row)
        if key:
            by_key[key].append(row)
    missing = defaultdict(list)
    for row, (district, _, _) in candidates(source, mapping):
        if not district:
            key = case_key(row)
            if key:
                missing[key].append(row)
    records = []
    for key, pending in missing.items():
        pending = unique_by_id(pending)
        pending_ids = {str(r["id"]) for r in pending}
        peers = unique_by_id([r for r in by_key[key] if str(r.get("id")) not in pending_ids])
        geo = []
        for row in peers:
            district, municipality, confidence = inferred_location(row, mapping)
            if district:
                geo.append({"source_id":row["id"],"district":district,
                            "municipality":municipality,"quality":confidence})
        # Do not infer target district from regional mentions or document titles.
        nearby = sorted({d["district"] for d in geo})
        title_hits = [
            r for r in peers if REG_DOC_PRIORITY.search(str(r.get("popis_udalosti") or ""))
        ]
        item = {
            "spis":key,
            "unknown_candidates":len(pending),
            "possibly_related_archived_rows":len(peers),
            "possibly_related_pdf_links":sum(
                bool(r.get("dokument_url")) for r in peers),
            "possibly_related_docs_with_location":len(geo),
            "related_districts_mentioned":nearby,
            "possibly_related_relevant_titles":len(title_hits),
            "event_sale_word_hits":sum(bool(REG_SALE.search(str(r.get("popis_udalosti") or "")))
                                        for r in peers),
            "source_rows":pending,
            "peer_rows":peers,
        }
        if geo: item["group"]="other_documents_have_a_location"
        elif peers: item["group"]="related_records_no_locality"
        else: item["group"]="no_other_archived_records"
        records.append(item)
    return records


def pick_cases(cases, limit=CASE_LIMIT):
    chosen = []
    taken = set()
    groups = ["other_documents_have_a_location", "related_records_no_locality",
              "no_other_archived_records"]
    for group in groups:
        entries = sorted((r for r in cases if r["group"] == group),
            key=lambda r: sha256(("isir-pilot-v1:" + r["spis"]).encode()).hexdigest())
        for row in entries[:limit // 3]:
            chosen.append(row)
            taken.add(row["spis"])
    # Rebalance when one cohort has fewer than ten matching cases.
    remaining = sorted((r for r in cases if r["spis"] not in taken),
        key=lambda r: sha256(("isir-pilot-v1:" + r["spis"]).encode()).hexdigest())
    chosen += remaining[:limit-len(chosen)]
    return chosen


def pdf_url(candidate):
    url = urlsplit(candidate or "")
    if url.scheme != "https" or url.hostname != "isir.justice.cz":
        raise ValueError("Not a permitted official ISIR HTTPS hostname")
    if url.port not in (443, 8443) or url.path != "/isir_public_ws/doc/Document":
        raise ValueError("Not a permitted ISIR document endpoint")
    values = parse_qs(url.query)
    if not (len(values.get("idDokument", [])) == 1 and
            values["idDokument"][0].isdigit() and len(values) == 1):
        raise ValueError("Invalid official ISIR document query")
    return candidate


def candidate_pdf(case):
    # At most one peer per sampled case: prefer an explicitly relevant event,
    # otherwise use one original unidentified document as a fallback.
    rows = [r for r in case["peer_rows"] if r.get("dokument_url")]
    rows.sort(key=lambda r: (0 if REG_DOC_PRIORITY.search(
        str(r.get("popis_udalosti") or "")) else 1,
        -(int(r["id"]) if str(r.get("id", "")).isdigit() else 0)))
    rows += [r for r in case["source_rows"] if r.get("dokument_url")]
    for row in rows:
        try:
            pdf_url(row["dokument_url"])
            return row
        except (ValueError, TypeError):
            pass
    return None


def extract_territory_names(page_text, mapping):
    found = set()
    for m in REG_KU.finditer(page_text or ""):
        raw = re.sub(r"[^a-z0-9 ]+", " ", normal(m.group(1))).strip()
        tokens = raw.split()
        # Require explicit cadastral-territory wording AND a valid CUZK name.
        for size in range(min(7, len(tokens)), 0, -1):
            name = " ".join(tokens[:size])
            # Mapping normalization includes punctuation, names mostly do not.
            if name in mapping:
                found.add(name)
                break
    return found


def inspect_pdf(row, mapping):
    result = {"source_id":str(row.get("id")),"status":"failed"}
    try:
        url = pdf_url(row.get("dokument_url"))
        request=Request(url,headers={"User-Agent":"ISIR-Radar-Pilot/1.0"})
        with urlopen(request,timeout=22) as resp:
            if resp.status != 200: raise ValueError("Unexpected PDF status")
            raw=resp.read(MAX_BYTES_PER_PDF + 1)
        if len(raw)>MAX_BYTES_PER_PDF: raise ValueError("PDF exceeds size cap")
        if not raw.startswith(b"%PDF"): raise ValueError("Source is not PDF")
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw), strict=False)
        all_pages=len(reader.pages)
        parsed=0
        text_pages=0
        extracted_names=set()
        count_parcel=count_lv=count_sale=0
        for page in reader.pages[:MAX_PAGES_PER_PDF]:
            parsed+=1
            t=page.extract_text() or ""
            text_pages+=bool(t.strip())
            extracted_names.update(extract_territory_names(t,mapping))
            count_parcel+=len(REG_PARCEL.findall(t))
            count_lv+=len(REG_LV.findall(t))
            count_sale+=len(REG_SALE.findall(t))
        districts=sorted({d for name in extracted_names
                          for d,_ in mapping.get(name,())})
        result.update({
            "status":"ok",
            "total_pdf_pages":all_pages,"pages_inspected":parsed,
            "pages_with_text":text_pages,
            "explicit_cadastral_names":len(extracted_names),
            "mentioned_districts":districts,
            "parcel_pattern_hits":count_parcel,
            "ownership_page_hits":count_lv,
            "sale_word_hits":count_sale,
            "sale_confirmed":False,
            "locality_confirmed":False,
        })
    except Exception as exc:
        result["error_type"]=type(exc).__name__
    return result


def execute(source, mapping, *, scan_pdfs=True):
    case_records=make_cases(source,mapping)
    sample=pick_cases(case_records,CASE_LIMIT)
    stats=Counter(r["group"] for r in case_records)
    sample_stats=Counter(r["group"] for r in sample)
    all_with_target_mentions=[r for r in case_records if
        set(r["related_districts_mentioned"]) & TARGETS]
    all_with_non_target_mentions=[r for r in case_records if
        r["related_districts_mentioned"] and
        not (set(r["related_districts_mentioned"]) & TARGETS)]
    indicators=[]
    for row in sample:
        peer_districts=row["related_districts_mentioned"]
        indicators.append({
            "spis":row["spis"],
            "group":row["group"],
            "unknown_candidate_documents":row["unknown_candidates"],
            "possibly_related_documents":row["possibly_related_archived_rows"],
            "possibly_related_pdfs":row["possibly_related_pdf_links"],
            "possibly_related_locality_documents":row["possibly_related_docs_with_location"],
            "related_district_mentions":peer_districts,
            "contains_target_district_mention":bool(set(peer_districts)&TARGETS),
            "title_sale_word_hits":row["event_sale_word_hits"],
        })
    pdf_probes=[]
    if scan_pdfs:
        # At most 12 official public PDFs, one per sampled case. Prioritize
        # cases with related documents, avoiding a nationwide bulk download.
        ordered=sorted(sample,key=lambda r:(
            r["group"]=="no_other_archived_records",
            not r["possibly_related_relevant_titles"],
            sha256(r["spis"].encode()).hexdigest()))
        for row in ordered:
            if len(pdf_probes)>=PDF_LIMIT:break
            candidate=candidate_pdf(row)
            if not candidate: continue
            res=inspect_pdf(candidate,mapping)
            res.update(spis=row["spis"],
                       source_is_related_document=(candidate in row["peer_rows"]))
            pdf_probes.append(res)
    return {
       "snapshot_updated_at":source.get("updated_at"),
       "archive_covers_cases":len(case_records),
       "cohort_all_counts":dict(stats),
       "all_cases_with_possible_target_district_mention":len(all_with_target_mentions),
       "all_unknown_candidate_docs_with_possible_target_mention":sum(
           r["unknown_candidates"] for r in all_with_target_mentions),
       "all_cases_with_only_non_target_district_mentions":len(all_with_non_target_mentions),
       "possible_target_cases":[{"spis":r["spis"],
           "district_mentions":r["related_districts_mentioned"],
           "unknown_candidate_docs":r["unknown_candidates"]}
           for r in all_with_target_mentions[:20]],
       "sample_size":len(sample),
       "cohort_sample_counts":dict(sample_stats),
       "selected_cases":indicators,
       "pdf_probe_limit":PDF_LIMIT,
       "pdf_probes":pdf_probes,
       "pdf_read_ok":sum(p["status"]=="ok" for p in pdf_probes),
       "pdf_with_any_text":sum(p["status"]=="ok" and p["pages_with_text"]>0 for p in pdf_probes),
       "pdf_with_explicit_cadastral_territory":sum(
           p["status"]=="ok" and p["explicit_cadastral_names"]>0 for p in pdf_probes),
       "pdf_with_target_district_mention":sum(
           p["status"]=="ok" and bool(set(p["mentioned_districts"])&TARGETS)
           for p in pdf_probes),
       "case_linkage_verified":False,
       "property_sale_verified":False,
       "db_modified":False,"old_crawler_started":False,
       "caveats":[
         "Matching incomplete INS case numbers may combine different court cases.",
         "Metadata and keyword hits are only investigative leads, not locality or sale confirmation.",
         "PDF checks scan no more than 12 pages; image-only pages are not OCR processed.",
         "Results are from the 2026-09-17 archive, not a fresh ISIR sweep."
       ]
    }


def main():
    source=json.loads((ROOT/"docs/results.json").read_text(encoding="utf-8"))
    mapping=territories()
    import os
    pdfs=os.getenv("PILOT_SCAN_PDFS","1") == "1"
    output=execute(source,mapping,scan_pdfs=pdfs)
    print("READ-ONLY HISTORIC ISIR RADAR PILOT — NO DB WRITE, NO CRAWLER")
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
