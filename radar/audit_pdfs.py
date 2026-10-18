"""Read-only check of the four public PDFs behind provisional Radar entries.
Downloads at most four bounded PDFs from the official ISIR host, scans extracted
text for document category and sales keywords; never logs personal names or text.
"""
from collections import Counter
import io
import json
import re
import urllib.parse
import urllib.request

from pypdf import PdfReader

from radar.import_legacy import ROOT, TARGETS, candidates, normal, territories

MAX_PDF_BYTES = 18_000_000
PATTERNS = {
 "sale_or_auction": r"\b(?:zpen[eě]ž(?:en[ií]|ov[aá]n[ií])|dražb(?:a|y|ě|ou)|prodej(?:e|i|em)?|kupn[ií]\s+cena|vyvol[aá]vac[ií]\s+cena)\b",
 "formal_estate_inventory": r"soupis.{0,50}majetkov.{0,25}podstat",
 "estate_property": r"\b(?:pozem(?:ek|ku|ky|ků)|parc(?:ela|ely|\.)|nemovitost(?:i|í|em)?|byt(?:u|y)|jednotk(?:a|y|u)|rodinn.{0,4}d[ůu]m)\b",
 "claims": r"přihl[aá]š(?:en.{0,15}pohled[aá]v|ka\s+pohled[aá]vk)",
 "ownership": r"(?:list\s+vlastnictv[ií]|\bLV\s*(?:[čc][ií]slo|[čc]\.)?\s*\d{1,7})",
}
REGEX={key:re.compile(expr,re.I|re.S) for key,expr in PATTERNS.items()}

def pdf_link(document_url):
    url=urllib.parse.urlsplit(document_url)
    if (url.scheme!="https" or url.hostname!="isir.justice.cz"
        or url.port not in (443,8443)
        or url.path!="/isir_public_ws/doc/Document"):
        raise ValueError("Not a pinned public ISIR PDF URL")
    parsed=urllib.parse.parse_qs(url.query)
    if not (len(parsed.get("idDokument",[]))==1
            and parsed["idDokument"][0].isdigit()):
        raise ValueError("Unrecognized ISIR document ID")
    return document_url

def document_stats(row):
    result={"id":row.get("id"),"spis":row.get("spisova_znacka"),
            "event_type":row.get("popis_udalosti"),
            "territories":row.get("katastralni_uzemi") or []}
    try:
        request=urllib.request.Request(pdf_link(row.get("dokument_url") or ""),
                                       headers={"User-Agent":"ISIR-Radar-ReadOnly-Audit/1.0"})
        with urllib.request.urlopen(request,timeout=35) as response:
            if response.status!=200:raise RuntimeError("ISIR PDF unavailable")
            raw=response.read(MAX_PDF_BYTES+1)
        if len(raw)>MAX_PDF_BYTES:raise ValueError("PDF size cap exceeded")
        if not raw.startswith(b"%PDF"):raise ValueError("ISIR document is not a PDF")
        pdf=PdfReader(io.BytesIO(raw))
        pages=pdf.pages
        # No OCR. This is deliberately a cheap audit of already text-analysed PDFs.
        counts=Counter()
        kucounts=Counter()
        textpages=0
        for page in pages:
            ptext=page.extract_text() or ""
            textpages+=bool(ptext.strip())
            normalized=normal(ptext)
            for name,pat in REGEX.items():
                counts[name]+=len(pat.findall(ptext))
            for ku in result["territories"]:
                if normal(ku) in normalized:kucounts[ku]+=1
        result.update({
          "read":"ok","pages":len(pages),
          "pages_with_text":textpages,
          "evidence_pattern_matches":dict(counts),
          "territory_mentioned_on_pages":dict(kucounts),
        })
        # Keyword signals alone never prove either a real sale or a specific asset.
        result["sale_confirmed"]=False
    except Exception as exc:
        result.update({"read":"failed","error_type":type(exc).__name__,
                       "sale_confirmed":False})
    return result

def main():
    source=json.loads((ROOT/"docs/results.json").read_text(encoding="utf-8"))
    selected=[r for r,loc in candidates(source,territories()) if loc[0] in TARGETS]
    if len(selected)!=4:
        raise RuntimeError(f"Unexpected candidate count: {len(selected)}; review safely")
    results=[document_stats(row) for row in selected]
    print("READ-ONLY PDF INDICATOR AUDIT; NOT A SALE VERIFICATION")
    print(json.dumps(results,ensure_ascii=False,indent=2))
    print("No crawler used. No user notes or original PDF text logged.")

if __name__=="__main__":
    main()
