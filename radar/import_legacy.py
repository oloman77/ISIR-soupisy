"""One-time bootstrap from historic ISIR candidates into isolated D1 radar catalog.

This does NOT start crawler, touch crawler cursor, deploy Pages or change source data.
A source document creates a provisional property candidate (isir-doc:<id>), never
pretending that one PDF proves a unique cadastral property. Manual decisions are
stored separately and are never reset by imports.
"""
import csv
import io
import json
import os
import unicodedata
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from d1_preflight import D1

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = Path(__file__).resolve().parent / "schema.sql"
TARGETS = {"Kutná Hora", "Havlíčkův Brod"}
TARGET_REGIONS = {"Středočeský kraj", "Kraj Vysočina", "Vysočina"}
CUZK_URL = "https://services.cuzk.cz/sestavy/cis/SC_SEZNAMKUKRA_DOTAZ.zip"


def normal(s):
    s = unicodedata.normalize("NFKD", str(s or "").casefold())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def territories():
    """KU name -> list of (district, municipality); never guess ambiguous names."""
    with urllib.request.urlopen(CUZK_URL, timeout=60) as response:
        raw = response.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not files:
            raise RuntimeError("CUZK archive contains no CSV")
        binary = archive.read(files[0])
    decoded = None
    for encoding in ("cp1250", "utf-8-sig", "utf-8"):
        try:
            decoded = binary.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise RuntimeError("Cannot decode CUZK CSV")
    first = decoded[:10000]
    delim = ";" if first.count(";") >= first.count(",") else ","
    mapping = {}
    for row in csv.DictReader(io.StringIO(decoded), delimiter=delim):
        name, district = row.get("KU_NAZEV", "").strip(), row.get("OKRES_NAZEV", "").strip()
        municipality = row.get("OBEC_NAZEV", "").strip()
        if name and district:
            mapping.setdefault(normal(name), set()).add((district, municipality))
    if len(mapping) < 1000:
        raise RuntimeError("CUZK lookup unexpectedly small; refusing import")
    return mapping


def inferred_location(row, mapping):
    pairs = set()
    for name in row.get("katastralni_uzemi") or []:
        pairs |= mapping.get(normal(name), set())
    districts = {x[0] for x in pairs}
    # A PDF may discuss other properties. Even unique matches are suggestions.
    if len(districts) == 1:
        district = next(iter(districts))
        municipality = next(iter({m for d,m in pairs if d == district})) if len(
            {m for d,m in pairs if d == district}) == 1 else ""
        return district, municipality, "suggested"
    return "", "", "unknown"


def relevant(row, located):
    if located[0] in TARGETS:
        return True
    if located[0]:
        return False
    regions = set(row.get("kraje") or [])
    if row.get("kraj"):
        regions.add(row["kraj"])
    # Preserve unknown localities for manual screening; never silently drop them.
    return not regions or bool(regions.intersection(TARGET_REGIONS))


def candidates(source, mapping):
    for row in source.get("items", []):
        if not (row.get("obsahuje_nemovitost") is True and
                row.get("pdf_status") == "ok" and row.get("dokument_url")):
            continue
        location = inferred_location(row, mapping)
        if not relevant(row, location):
            continue
        yield row, location


def run():
    cloud = D1()
    name = cloud.request().get("name")
    if name != "isir-radar":
        raise RuntimeError("Refusing to import: dedicated database must be named isir-radar")
    # Old result file may exceed 100 MB; read it only in the GitHub Action,
    # never serve it to a browser.
    source = json.loads((ROOT / "docs/results.json").read_text(encoding="utf-8"))
    if not isinstance(source.get("items"), list):
        raise RuntimeError("Legacy results file invalid")
    mapping = territories()
    sql = SCHEMA.read_text(encoding="utf-8")
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement and not statement.startswith("--"):
            cloud.query(statement)
        elif statement.startswith("--"):
            cleaned = "\n".join(line for line in statement.splitlines()
                                if not line.lstrip().startswith("--")).strip()
            if cleaned:
                cloud.query(cleaned)

    total, matched, unknown = 0, 0, 0
    for row, (district, municipality, confidence) in candidates(source, mapping):
        rid = int(row["id"])
        prop_id = "isir-doc:" + str(rid)
        spis = (row.get("spisova_znacka") or "nezjištěný spis").strip()
        title = ("Nemovitost v řízení " + spis)[:180]
        ku = ", ".join((row.get("katastralni_uzemi") or [])[:4])[:160]
        descr = (row.get("popis_udalosti") or "Dokument z ISIR")[:180]
        published = (row.get("datum_zverejneni") or row.get("datum_zalozeni") or "")[:35]
        pdf = str(row.get("dokument_url") or "")[:1000]
        court_link = str(row.get("isir_rizeni_url") or row.get("isir_search_url") or "")[:1000]
        note = ", ".join(row.get("nemovitost_signaly") or [])[:480]
        cloud.query(
            "INSERT INTO properties (id,title,property_type,district,municipality,"
            "cadastral_territory,location_confidence) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title,"
            "district=excluded.district,municipality=excluded.municipality,"
            "cadastral_territory=excluded.cadastral_territory,"
            "location_confidence=excluded.location_confidence,"
            "updated_at=datetime('now')",
            (prop_id,title,"nezjištěno",district,municipality,ku,confidence)
        )
        cloud.query(
            "INSERT INTO property_sources (id,property_id,source_type,external_id,"
            "source_title,source_url,published_at,raw_excerpt) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET source_title=excluded.source_title,"
            "source_url=excluded.source_url,raw_excerpt=excluded.raw_excerpt,"
            "last_seen_at=datetime('now')",
            ("isir-pdf:"+str(rid),prop_id,"isir",str(rid),descr,pdf,published,note)
        )
        # The additional case link is optional, does not replace the PDF source.
        if court_link.startswith(("http://", "https://")):
            cloud.query(
                "INSERT INTO property_sources (id,property_id,source_type,external_id,"
                "source_title,source_url) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET source_url=excluded.source_url",
                ("isir-case:"+str(rid),prop_id,"isir-rizeni","case:"+str(rid),
                 "Celé insolvenční řízení",court_link)
            )
        total += 1
        matched += bool(district)
        unknown += not bool(district)
        if total % 100 == 0:
            print("Imported",total,"candidates; target-district suggestions",matched,flush=True)
    if not total:
        raise RuntimeError("No relevant candidate documents found, import stopped")
    actual = cloud.query("SELECT COUNT(*) AS n FROM properties WHERE id LIKE 'isir-doc:%'")[0]["n"]
    if actual < total:
        raise RuntimeError("Remote D1 verification failed: imported less than expected")
    print(json.dumps({
        "imported_provisional_candidates":total,"suggested_target_district":matched,
        "district_unknown":unknown,"total_in_d1":actual,
        "source_snapshot_updated_at":source.get("updated_at"),
        "finished_utc":datetime.now(timezone.utc).isoformat(),
        "manual_decisions_untouched":True,
        "crawler_started":False
    },ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":
    run()
