import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

SERVICE_URL = "https://isir.justice.cz:8443/isir_public_ws/IsirWsPublicService"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
STATE_FILE = DATA_DIR / "state.json"
RESULTS_FILE = DOCS_DIR / "results.json"

DAYS_BACK = int(os.getenv("DAYS_BACK", "30"))
MAX_BATCHES = int(os.getenv("MAX_BATCHES", "1500"))
PAUSE = float(os.getenv("PAUSE", "0.10"))

SOUPIS_RX = re.compile(
    r"(soupis.{0,50}majetkov[ée].{0,30}podstat|dopln[eě]n[ií].{0,50}soupis|aktualizovan[ýá].{0,50}soupis|zm[eě]na.{0,50}soupis|dodatek.{0,50}soupis|soupis\s+majetku)",
    re.I | re.S
)

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
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def soap(body, timeout=90):
    env = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:typ="http://isirpublicws.cca.cz/types/">'
        '<soapenv:Header/><soapenv:Body>' + body + '</soapenv:Body></soapenv:Envelope>'
    )
    r = requests.post(
        SERVICE_URL,
        data=env.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
        timeout=timeout,
    )
    r.raise_for_status()
    return ET.fromstring(r.content)

def get_last_id():
    root = soap("<typ:getIsirWsPublicPosledniIdDataRequest/>")
    for el in root.iter():
        if lname(el.tag) == "cisloPosledniId":
            return int((el.text or "0").strip())
    raise RuntimeError("ISIR nevrátil cisloPosledniId")

def get_after_id(i):
    root = soap(
        f"<typ:getIsirWsPublicIdDataRequest><idPodnetu>{int(i)}</idPodnetu></typ:getIsirWsPublicIdDataRequest>"
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
    rows.sort(key=lambda x: x["id"])
    return rows

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
        row = rows[0]
        dt = parse_dt(row["datum_zverejneni"]) or parse_dt(row["datum_zalozeni"])
        if dt is None:
            hi = mid - 1
            continue
        if dt < cutoff:
            best = row["id"]
            lo = mid + 1
        else:
            hi = mid - 1
        time.sleep(PAUSE)
    return max(0, best - 2000)

def main():
    DATA_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=DAYS_BACK)

    state = load_json(STATE_FILE, {})
    results = load_json(RESULTS_FILE, {"updated_at": None, "items": []})
    existing = {str(x.get("id")): x for x in results.get("items", []) if x.get("id") is not None}

    latest = get_last_id()
    current = state.get("current_id")

    if not current:
        print("První běh: hledám začátek období…", flush=True)
        current = locate_cutoff_id(cutoff, latest)
        print("Start ID:", current, flush=True)
    else:
        print("Navazuji od ID:", current, flush=True)

    batches = 0
    processed = 0

    while current < latest and batches < MAX_BATCHES:
        rows = get_after_id(current)
        batches += 1
        if not rows:
            break
        progressed = False
        for row in rows:
            rid = row["id"]
            if rid <= current:
                continue
            progressed = True
            current = max(current, rid)
            processed += 1
            dt = parse_dt(row["datum_zverejneni"]) or parse_dt(row["datum_zalozeni"])
            if dt and dt >= cutoff and is_soupis(row):
                existing[str(rid)] = row
        print(f"dávka {batches} | current={current} | processed={processed} | results={len(existing)}", flush=True)
        if not progressed:
            break
        time.sleep(PAUSE)

    filtered = []
    for row in existing.values():
        dt = parse_dt(row.get("datum_zverejneni")) or parse_dt(row.get("datum_zalozeni"))
        if dt and dt >= cutoff:
            filtered.append(row)

    filtered.sort(
        key=lambda r: parse_dt(r.get("datum_zverejneni")) or parse_dt(r.get("datum_zalozeni")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )

    save_json(STATE_FILE, {
        "current_id": current,
        "latest_id_at_run": latest,
        "last_run": now.isoformat(),
        "days_back": DAYS_BACK,
        "caught_up": current >= latest
    })

    save_json(RESULTS_FILE, {
        "updated_at": now.isoformat(),
        "days_back": DAYS_BACK,
        "current_id": current,
        "latest_id": latest,
        "caught_up": current >= latest,
        "count": len(filtered),
        "items": filtered
    })

if __name__ == "__main__":
    main()
