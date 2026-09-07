import io
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
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "40"))

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
    for row in csv.DictReader(io.StringIO(text), delimiter=delim):
        ku = (row.get("KU_NAZEV") or "").strip()
        office = (row.get("PRARES_NAZEV") or "").strip()
        if ku and office:
            mp[norm(ku)] = {
                "ku_nazev": ku,
                "obec": (row.get("OBEC_NAZEV") or "").strip(),
                "pracoviste": office,
            }

    print(f"ČÚZK: načteno {len(mp)} katastrálních území", flush=True)
    return mp

def pdf_text(url):
    if not url:
        return "", "no_url"
    try:
        r = SESSION.get(url, timeout=PDF_TIMEOUT)
        r.raise_for_status()

        ctype = (r.headers.get("content-type") or "").lower()
        if "pdf" not in ctype and not r.content.startswith(b"%PDF"):
            return "", "not_pdf"

        reader = PdfReader(io.BytesIO(r.content))
        parts = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                pass

        text = "\n".join(parts).strip()
        if not text:
            return "", "no_text"

        return text, "ok"

    except Exception as e:
        return "", "error:" + type(e).__name__

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

def extract_ku(text, mp):
    found = {}
    for rx in KU_RX:
        for m in rx.finditer(text or ""):
            cand = re.split(r"[,;\n\r\(\)]", m.group(1), maxsplit=1)[0].strip(" .:-")
            n = norm(cand)
            if n in mp:
                found[n] = mp[n]
    return list(found.values())

def enrich(row, mp):
    text, status = pdf_text(row.get("dokument_url"))
    yes, hits = detect_real(text)
    infos = extract_ku(text, mp)

    row["pdf_checked"] = True
    row["pdf_status"] = status
    row["obsahuje_nemovitost"] = bool(status == "ok" and yes)
    row["nemovitost_signaly"] = hits if status == "ok" else []
    row["katastralni_uzemi"] = sorted({x["ku_nazev"] for x in infos})
    row["obce"] = sorted({x["obec"] for x in infos if x["obec"]})
    row["katastralni_pracoviste"] = sorted({x["pracoviste"] for x in infos})
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

    if not current or previous_days < DAYS_BACK:
        print(
            f"FÁZE 1: backfill {previous_days} -> {DAYS_BACK} dní. Hledám start…",
            flush=True,
        )
        current = locate_cutoff_id(cutoff, latest)
        print(f"Historický start ID: {current}", flush=True)

    caught_up_before = current >= latest
    batches = 0
    processed = 0

    if not caught_up_before:
        print("FÁZE 1: rychlé procházení ISIR bez PDF analýzy", flush=True)

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
                if dt and dt >= cutoff and is_soupis(row):
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

    caught_up = current >= latest

    # Uchovej jen položky v 180denním okně.
    valid_keys = []
    for key, row in existing.items():
        dt = parse_dt(row.get("datum_zverejneni")) or parse_dt(row.get("datum_zalozeni"))
        if dt and dt >= cutoff:
            valid_keys.append(key)

    # FÁZE 2 se spustí AŽ po dotažení ISIR historie.
    pdf_done_this_run = 0

    if caught_up:
        print("FÁZE 2: historie ISIR dotažena, spouštím PDF analýzu", flush=True)
        mp = load_cuzk()

        todo = [
            key for key in valid_keys
            if not existing[key].get("pdf_checked")
        ]
        this_run = todo[:MAX_PDF_PER_RUN]

        print(
            f"PDF čeká celkem: {len(todo)} | "
            f"v tomto běhu: {len(this_run)}",
            flush=True,
        )

        for i, key in enumerate(this_run, 1):
            existing[key] = enrich(existing[key], mp)
            pdf_done_this_run = i

            if i % 10 == 0 or i == len(this_run):
                confirmed_now = sum(
                    1 for k in valid_keys
                    if existing[k].get("obsahuje_nemovitost") is True
                )
                print(
                    f"PDF {i}/{len(this_run)} | potvrzené nemovitosti={confirmed_now}",
                    flush=True,
                )
    else:
        print(
            "PDF analýza přeskočena – nejdřív dokončíme FÁZI 1.",
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
        if not x.get("pdf_checked")
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

    phase = "pdf_analysis" if caught_up and remaining_pdf > 0 else (
        "complete" if caught_up and remaining_pdf == 0 else "isir_backfill"
    )

    save_json(STATE_FILE, {
        "current_id": current,
        "latest_id_at_run": latest,
        "last_run": now.isoformat(),
        "days_back": DAYS_BACK,
        "caught_up": caught_up,
        "phase": phase,
    })

    save_json(RESULTS_FILE, {
        "updated_at": now.isoformat(),
        "days_back": DAYS_BACK,
        "current_id": current,
        "latest_id": latest,
        "caught_up": caught_up,
        "phase": phase,
        "count_all_soupisy": len(valid),
        "count_real_estate": len(confirmed),
        "remaining_pdf_analysis": remaining_pdf,
        "katastralni_pracoviste_options": offices,
        "items": valid,
    })

    print(
        f"BĚH HOTOV | phase={phase} | current={current}/{latest} | "
        f"soupisy={len(valid)} | nemovitosti={len(confirmed)} | "
        f"PDF čeká={remaining_pdf} | PDF dnes={pdf_done_this_run}",
        flush=True,
    )

if __name__ == "__main__":
    main()
