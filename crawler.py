import io
import subprocess
import tempfile
import csv
import json
import os
import re
import time
import zipfile
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pypdf import PdfReader

SERVICE_URL = "https://isir.justice.cz:8443/isir_public_ws/IsirWsPublicService"
CUZK_KU_URL = "https://services.cuzk.cz/sestavy/cis/SC_SEZNAMKUKRA_DOTAZ.zip"

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data/state.json"
RESULTS_FILE = ROOT / "docs/results.json"

DAYS_BACK = int(os.getenv("DAYS_BACK", "180"))
MAX_BATCHES = int(os.getenv("MAX_BATCHES", "250"))
MAX_PDF_PER_RUN = int(os.getenv("MAX_PDF_PER_RUN", "150"))
PAUSE = float(os.getenv("PAUSE", "0.05"))
SOAP_TIMEOUT = int(os.getenv("SOAP_TIMEOUT", "45"))
PDF_TIMEOUT = int(os.getenv("PDF_TIMEOUT", "25"))

SOUPIS_RX = re.compile(
    r"(soupis.{0,50}majetkov[ée].{0,30}podstat|"
    r"dopln[eě]n[ií].{0,50}soupis|"
    r"aktualizovan[ýá].{0,50}soupis|"
    r"zm[eě]na.{0,50}soupis|"
    r"dodatek.{0,50}soupis|"
    r"soupis\s+majetku)",
    re.I | re.S,
)

REAL_PATTERNS = [
    r"katastr[aá]ln[ií]\s+[úu]zem[ií]",
    r"list\s+vlastnictv[ií]",
    r"\bLV\s*(?:č\.?|číslo)?\s*\d+",
    r"parc(?:ela|ely|\.?)\s*(?:č\.?|číslo)?\s*[\d/]+",
    r"\bpozemek\b",
    r"\bstavba\b",
    r"\bjednotka\b",
    r"\bbyt\b",
    r"rodinn[ýy]\s+d[ůu]m",
    r"\bnemovitost",
    r"\bgar[aá][žz]\b",
]

KU_RX = [
    re.compile(
        r"katastr[aá]ln[ií]\s+[úu]zem[ií]\s*[:\-]?\s*"
        r"([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][A-Za-zÁ-ž0-9 .'\-]{1,70})",
        re.I,
    ),
    re.compile(
        r"\bk\.\s*[úu]\.\s*[:\-]?\s*"
        r"([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][A-Za-zÁ-ž0-9 .'\-]{1,70})",
        re.I,
    ),
]

OFFICE_RX = [
    re.compile(
        r"katastr[aá]ln[ií]\s+pracovi[sš]t[eě]\s*[:\-]?\s*"
        r"([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][A-Za-zÁ-ž .'\-]{1,80})",
        re.I,
    ),
]

def build_session():
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s = requests.Session()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

SESSION = build_session()

def lname(tag):
    return tag.split("}", 1)[-1]

def find_text(el, name):
    for ch in el.iter():
        if lname(ch.tag) == name:
            return (ch.text or "").strip()
    return ""

def extract_id_osoby_puvodce(el):
    raw = find_text(el, "poznamka")
    if not raw:
        try:
            raw = ET.tostring(el, encoding="unicode")
        except Exception:
            raw = ""
    m = re.search(r"<(?:\\w+:)?idOsobyPuvodce>\\s*([^<]+?)\\s*</(?:\\w+:)?idOsobyPuvodce>", raw, re.I)
    return m.group(1).strip() if m else ""

def parse_dt(s):
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def soap(body):
    env = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:typ="http://isirpublicws.cca.cz/types/">'
        '<soapenv:Header/><soapenv:Body>' + body + '</soapenv:Body></soapenv:Envelope>'
    )
    r = SESSION.post(
        SERVICE_URL,
        data=env.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
        timeout=SOAP_TIMEOUT,
    )
    r.raise_for_status()
    return ET.fromstring(r.content)

def get_last_id():
    root = soap("<typ:getIsirWsPublicPosledniIdDataRequest/>")
    for el in root.iter():
        if lname(el.tag) == "cisloPosledniId":
            return int((el.text or "0").strip())
    raise RuntimeError("ISIR nevrátil poslední ID")

def get_after_id(i):
    root = soap(
        f"<typ:getIsirWsPublicIdDataRequest>"
        f"<idPodnetu>{int(i)}</idPodnetu>"
        f"</typ:getIsirWsPublicIdDataRequest>"
    )
    rows = []
    for el in root.iter():
        if lname(el.tag) != "data":
            continue
        rid = find_text(el, "id")
        if not rid.isdigit():
            continue
        rows.append({
            "id": int(rid),
            "datum_zverejneni": find_text(el, "datumZverejneniUdalosti"),
            "datum_zalozeni": find_text(el, "datumZalozeniUdalosti"),
            "spisova_znacka": find_text(el, "spisovaZnacka"),
            "typ_udalosti": find_text(el, "typUdalosti"),
            "popis_udalosti": find_text(el, "popisUdalosti"),
            "poznamka": find_text(el, "poznamka"),
            "dokument_url": find_text(el, "dokumentUrl"),
            "id_osoby_puvodce": extract_id_osoby_puvodce(el),
        })
    return sorted(rows, key=lambda x: x["id"])

def is_soupis(row):
    text = (row.get("popis_udalosti") or "") + "\n" + (row.get("poznamka") or "")
    return bool(SOUPIS_RX.search(text))

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def locate_cutoff_id(cutoff, latest):
    lo, hi, best = 0, latest, 0
    for _ in range(28):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        rows = get_after_id(mid)
        if not rows:
            hi = mid - 1
            continue
        dt = parse_dt(rows[0]["datum_zverejneni"]) or parse_dt(rows[0]["datum_zalozeni"])
        if not dt:
            hi = mid - 1
            continue
        if dt < cutoff:
            best = rows[0]["id"]
            lo = mid + 1
        else:
            hi = mid - 1
        time.sleep(PAUSE)
    return max(0, best - 2000)

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def load_cuzk():
    r = SESSION.get(CUZK_KU_URL, timeout=45)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError("ČÚZK ZIP neobsahuje CSV")
        raw = z.read(names[0])

    text = None
    for enc in ("cp1250", "utf-8-sig", "utf-8", "latin1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise RuntimeError("Nelze dekódovat ČÚZK CSV")

    delim = ";" if text[:10000].count(";") >= text[:10000].count(",") else ","
    mp = {}
    office_map = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=delim):
        ku = (row.get("KU_NAZEV") or "").strip()
        office = (row.get("PRARES_NAZEV") or "").strip()
        if ku and office:
            mp[norm(ku)] = {
                "ku_nazev": ku,
                "obec": (row.get("OBEC_NAZEV") or "").strip(),
                "pracoviste": office,
            }
            office_map[norm(office)] = office

    print(
        f"ČÚZK: načteno {len(mp)} katastrálních území, "
        f"{len(office_map)} pracovišť",
        flush=True,
    )
    return mp, office_map

def pdf_text(url):
    if not url:
        return "", "no_url"
    parts = []
    started = time.monotonic()
    try:
        r = SESSION.get(url, timeout=PDF_TIMEOUT)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            return "", "not_pdf"
        reader = PdfReader(io.BytesIO(r.content))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            source.write_bytes(r.content)
            # Read every page. Low-text pages need OCR even in mixed PDFs.
            for number, page in enumerate(reader.pages, 1):
                if time.monotonic() - started > 120:
                    return "\n".join(parts), "partial:time_limit"
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if len(text.strip()) < 100:
                    prefix = str(Path(tmp) / "page")
                    subprocess.run(
                        ["pdftoppm", "-f", str(number), "-l", str(number),
                         "-singlefile", "-scale-to", "2400", "-png", str(source), prefix],
                        check=True, capture_output=True, timeout=30,
                    )
                    result = subprocess.run(
                        ["tesseract", prefix + ".png", "stdout", "-l", "ces+eng"],
                        check=True, capture_output=True, timeout=45,
                    )
                    ocr = result.stdout.decode("utf-8", errors="replace").strip()
                    text = text + "\n" + ocr
                parts.append(text)
        text = "\n".join(parts).strip()
        return (text, "ok") if text else ("", "no_text")
    except Exception as e:
        return "\n".join(parts), "error:" + type(e).__name__


def needs_analysis(row):
    return (not row.get("pdf_checked")
            or row.get("pdf_status") != "ok"
            or int(row.get("enrichment_version") or 0) < 10)


def retry_due(row, now):
    due = parse_dt(row.get("pdf_retry_after"))
    return due is None or due <= now


def detect_real(text):
    hits = []
    for pat in REAL_PATTERNS:
        m = re.search(pat, text or "", re.I)
        if m:
            hits.append(m.group(0))

    uniq, seen = [], set()
    for h in hits:
        k = norm(h)
        if k not in seen:
            seen.add(k)
            uniq.append(h)

    return len(uniq) >= 2, uniq[:8]

def normalize_pdf_text(text):
    t = (text or "").replace("\u00a0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    return t

KRAJ_RX = re.compile(
    # Podporuje běžné pády:
    # "Katastrální úřad pro ..."
    # "Katastrálním úřadem pro ..."
    # "Katastrálního úřadu pro ..."
    r"katastr[aá]ln(?:[ií]|[ií]m|[ií]ho)\s+"
    r"[úu]řad(?:em|u)?\s+pro\s+"
    r"([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][A-Za-zÁ-ž\- ]{2,60}?\s+kraj)",
    re.I,
)

STRONG_REAL_PATTERNS = [
    r"katastr[aá]ln[ií]\s+[úu]řad\s+pro",
    r"list\s+vlastnictv[ií]",
    r"\bLV\s*(?:č\.?|číslo)?\s*\d+",
    r"\bnemovitost",
    r"parc(?:ela|ely|\.?)\s*(?:č\.?|číslo)?\s*[\d/]+",
]

def detect_suspicion(text):
    """
    V7 záměrně neurčuje přesnou nemovitost. Jen označí PDF,
    kde jsou rozumné signály, že dokument obsahuje nemovitý majetek.
    """
    t = normalize_pdf_text(text)
    hits = []

    for pat in REAL_PATTERNS:
        m = re.search(pat, t, re.I)
        if m:
            hits.append(m.group(0))

    strong = any(re.search(p, t, re.I) for p in STRONG_REAL_PATTERNS)

    uniq, seen = [], set()
    for h in hits:
        k = norm(h)
        if k not in seen:
            seen.add(k)
            uniq.append(h)

    suspected = strong or len(uniq) >= 2
    return suspected, uniq[:8]

def extract_kraj(text):
    """
    Vezme první přímý údaj typu 'Katastrální úřad pro ... kraj'.
    Hledáme jen v první části dokumentu, abychom omezili vliv referenčních
    nemovitostí ve znaleckých přílohách.
    """
    t = normalize_pdf_text(text)[:30000]
    m = KRAJ_RX.search(t)
    if not m:
        return ""

    raw = re.sub(r"\s+", " ", m.group(1)).strip(" .,:;-")
    # Hezčí kapitalizace zachovávající českou diakritiku.
    parts = raw.split()
    return " ".join(p[:1].upper() + p[1:] for p in parts)

def isir_search_url(row):
    spis = row.get("spisova_znacka") or ""
    m = re.search(r"\bINS\s+(\d+)\s*/\s*(\d{4})\b", spis, re.I)
    if not m:
        return "https://isir.justice.cz/isir/common/index.do"

    params = {
        "nazev_osoby": "",
        "jmeno_osoby": "",
        "ic": "",
        "datum_narozeni": "",
        "rc": "",
        "mesto": "",
        "cislo_senatu": "",
        "bc_vec": m.group(1),
        "rocnik": m.group(2),
        "id_osoby_puvodce": row.get("id_osoby_puvodce") or "",
        "druh_stav_konkursu": "",
        "datum_stav_od": "",
        "datum_stav_do": "",
        "aktualnost": "AKTUALNI_I_UKONCENA",
        "druh_kod_udalost": "",
        "datum_akce_od": "",
        "datum_akce_do": "",
        "nazev_osoby_f": "",
        "cislo_senatu_vsns": "",
        "druh_vec_vsns": "",
        "bc_vec_vsns": "",
        "rocnik_vsns": "",
        "cislo_senatu_icm": "",
        "bc_vec_icm": "",
        "rocnik_icm": "",
        "rowsAtOnce": "50",
        "spis_znacky_datum": "",
        "spis_znacky_obdobi": "14DNI",
    }
    return requests.Request(
        "GET",
        "https://isir.justice.cz/isir/ueu/vysledek_lustrace.do",
        params=params,
    ).prepare().url


def resolve_isir_detail(row):
    search_url = isir_search_url(row)
    row["isir_search_url"] = search_url

    try:
        r = SESSION.get(search_url, timeout=20)
        r.raise_for_status()
        html = r.text

        patterns = [
            r"""href=["']([^"']*evidence_upadcu_detail\.do\?id=[^"']+)["']""",
            r'(https?://isir\.justice\.cz/isir/ueu/evidence_upadcu_detail\.do\?id=[A-Za-z0-9\-]+)',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                return urljoin("https://isir.justice.cz/isir/ueu/", m.group(1))
    except Exception as e:
        print(f"ISIR detail lookup selhal pro {row.get('spisova_znacka')}: {e}", flush=True)

    return ""

def enrich(row, mp=None, office_map=None):
    text, status = pdf_text(row.get("dokument_url"))

    suspected, hits = detect_suspicion(text) if status == "ok" else (False, [])
    kraj = extract_kraj(text) if status == "ok" and suspected else ""
    detail_url = resolve_isir_detail(row) if status == "ok" and suspected else ""

    row["pdf_checked"] = status == "ok"
    attempts = int(row.get("pdf_attempts") or 0) + 1
    row["pdf_attempts"] = attempts
    row["pdf_last_attempt"] = datetime.now(timezone.utc).isoformat()
    row["pdf_retry_after"] = (
        (datetime.now(timezone.utc) + timedelta(hours=min(24, 2 ** min(attempts, 5)))).isoformat()
        if status != "ok" else None
    )
    row["review_status"] = "candidate" if suspected else ("no_signal" if status == "ok" else "unread")
    row["pdf_status"] = status
    row["obsahuje_nemovitost"] = bool(status == "ok" and suspected)
    row["nemovitost_signaly"] = hits if status == "ok" else []
    row["kraj"] = kraj
    row["isir_rizeni_url"] = detail_url

    # Staré detailní údaje už ve v7 nepoužíváme.
    row["katastralni_uzemi"] = []
    row["katastralni_pracoviste"] = []
    row["obce"] = []
    row["lv"] = []
    row["parcely"] = []
    row["typy_nemovitosti"] = []

    row["enrichment_version"] = 10
    return row

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=DAYS_BACK)

    state = load_json(STATE_FILE, {})
    old = load_json(RESULTS_FILE, {"items": []})
    existing = {
        str(x.get("id")): x
        for x in old.get("items", [])
        if x.get("id") is not None
    }

    latest = get_last_id()
    previous_days = int(state.get("days_back") or 0)
    current = state.get("current_id")

    backfill_complete = bool(state.get("backfill_complete")) or any(
        x.get("pdf_checked") for x in existing.values()
    ) or state.get("phase") in ("pdf_analysis", "complete")

    if not current or previous_days < DAYS_BACK:
        print(
            f"FÁZE 1: backfill {previous_days} -> {DAYS_BACK} dní. Hledám start…",
            flush=True,
        )
        current = locate_cutoff_id(cutoff, latest)
        backfill_complete = False
        print(f"Historický start ID: {current}", flush=True)

    coverage_start = state.get("all_documents_from_id", current)
    analysis_deadline = time.monotonic() + 900
    batches = 0
    processed = 0

    if current < latest:
        print(
            "BĚŽNÁ AKTUALIZACE: stahuji nové ISIR události"
            if backfill_complete
            else "FÁZE 1: rychlé procházení ISIR bez PDF analýzy",
            flush=True,
        )

        while current < latest and batches < MAX_BATCHES:
            rows = get_after_id(current)
            batches += 1
            if not rows:
                break

            progressed = False
            for row in rows:
                if row["id"] <= current:
                    continue

                progressed = True
                current = max(current, row["id"])
                processed += 1

                dt = parse_dt(row["datum_zverejneni"]) or parse_dt(row["datum_zalozeni"])
                if dt and dt >= cutoff and (row.get("dokument_url") or is_soupis(row)):
                    key = str(row["id"])
                    if key in existing:
                        for k, v in existing[key].items():
                            if k not in row:
                                row[k] = v
                    existing[key] = row

            print(
                f"ISIR {batches}/{MAX_BATCHES} | current={current}/{latest} | "
                f"processed={processed} | soupisy={len(existing)}",
                flush=True,
            )

            if not progressed:
                break

            time.sleep(PAUSE)

    caught_up_now = current >= latest
    if caught_up_now:
        backfill_complete = True

    valid_keys = []
    for key, row in existing.items():
        dt = parse_dt(row.get("datum_zverejneni")) or parse_dt(row.get("datum_zalozeni"))
        if dt and dt >= cutoff:
            valid_keys.append(key)

    pdf_done_this_run = 0

    if backfill_complete:
        print("FÁZE 2: analyzuji dokumenty", flush=True)
        todo = [key for key in valid_keys
                if needs_analysis(existing[key]) and retry_due(existing[key], now)]
        # Previously attempted rows go behind new documents; oldest new first.
        todo.sort(key=lambda key: (int(existing[key].get("pdf_attempts") or 0),
                                   int(existing[key]["id"])))
        this_run = todo[:MAX_PDF_PER_RUN]

        print(
            f"PDF čeká celkem: {len(todo)} | "
            f"v tomto běhu: {len(this_run)}",
            flush=True,
        )

        for i, key in enumerate(this_run, 1):
            if time.monotonic() >= analysis_deadline:
                break
            existing[key] = enrich(existing[key])
            pdf_done_this_run = i

            if i % 10 == 0 or i == len(this_run):
                confirmed_now = sum(
                    1 for k in valid_keys
                    if existing[k].get("obsahuje_nemovitost") is True
                )
                print(
                    f"PDF {i}/{len(this_run)} | možné nemovitosti={confirmed_now}",
                    flush=True,
                )
    else:
        print(
            "PDF analýza přeskočena – nejdřív dokončíme historický backfill.",
            flush=True,
        )

    valid = [existing[k] for k in valid_keys]
    valid.sort(
        key=lambda r:
            parse_dt(r.get("datum_zverejneni"))
            or parse_dt(r.get("datum_zalozeni"))
            or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    remaining_pdf = sum(
        1 for x in valid
        if needs_analysis(x)
    )

    confirmed = [
        x for x in valid
        if x.get("obsahuje_nemovitost") is True
        and x.get("pdf_status") == "ok"
        and x.get("dokument_url")
    ]

    offices = sorted({
        office
        for x in confirmed
        for office in (x.get("katastralni_pracoviste") or [])
    })

    if not backfill_complete:
        phase = "isir_backfill"
    elif not caught_up_now:
        phase = "catching_up"
    elif remaining_pdf > 0:
        phase = "pdf_analysis"
    else:
        phase = "complete"

    save_json(STATE_FILE, {
        "all_documents_from_id": coverage_start,
        "current_id": current,
        "latest_id_at_run": latest,
        "last_run": now.isoformat(),
        "days_back": DAYS_BACK,
        "caught_up": caught_up_now,
        "backfill_complete": backfill_complete,
        "phase": phase,
    })

    save_json(RESULTS_FILE, {
        "updated_at": now.isoformat(),
        "days_back": DAYS_BACK,
        "all_documents_from_id": coverage_start,
        "current_id": current,
        "latest_id": latest,
        "caught_up": caught_up_now,
        "backfill_complete": backfill_complete,
        "phase": phase,
        "count_all_soupisy": sum(is_soupis(x) for x in valid),
        "count_all_documents": len(valid),
        "failed_pdf_analysis": sum(needs_analysis(x) and bool(x.get("pdf_attempts")) for x in valid),
        "count_real_estate": len(confirmed),
        "remaining_pdf_analysis": remaining_pdf,
        "katastralni_pracoviste_options": offices,
        "items": valid,
    })

    print(
        f"BĚH HOTOV | phase={phase} | current={current}/{latest} | "
        f"backfill_complete={backfill_complete} | "
        f"soupisy={len(valid)} | nemovitosti={len(confirmed)} | "
        f"PDF čeká={remaining_pdf} | PDF dnes={pdf_done_this_run}",
        flush=True,
    )

if __name__ == "__main__":
    main()

