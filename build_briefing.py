import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS_FILE = ROOT / "docs/results.json"
BRIEFING_FILE = ROOT / "docs/briefing.json"


def parse_dt(value):
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)
    source = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

    items = []
    for row in source.get("items", []):
        dt = parse_dt(row.get("datum_zverejneni")) or parse_dt(row.get("datum_zalozeni"))
        if not dt or dt < cutoff:
            continue
        if row.get("obsahuje_nemovitost") is not True:
            continue
        if row.get("pdf_checked") is not True or row.get("pdf_status") != "ok":
            continue
        if not row.get("dokument_url"):
            continue

        # Keep only fields useful for the scheduled briefing. This deliberately
        # avoids copying large OCR/resume payloads from results.json.
        items.append({
            key: row.get(key)
            for key in (
                "id", "datum_zverejneni", "datum_zalozeni", "spisova_znacka",
                "typ_udalosti", "popis_udalosti", "dokument_url",
                "obsahuje_nemovitost", "pdf_checked", "pdf_status",
                "nemovitost_signaly", "kraj", "kraje", "obce",
                "katastralni_uzemi", "katastralni_pracoviste",
                "lokalita_doklady", "isir_rizeni_url", "isir_search_url",
            )
            if row.get(key) not in (None, "", [], {})
        })

    items.sort(
        key=lambda row: parse_dt(row.get("datum_zverejneni"))
        or parse_dt(row.get("datum_zalozeni"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    payload = {
        "updated_at": now.isoformat(),
        "window_hours": 48,
        "source_updated_at": source.get("updated_at"),
        "count": len(items),
        "items": items,
    }
    BRIEFING_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"briefing.json: {len(items)} potvrzených nemovitostí za 48 hodin")


if __name__ == "__main__":
    main()
