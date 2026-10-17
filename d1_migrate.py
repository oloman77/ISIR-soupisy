"""One-time, resumable D1 import. Never modifies GitHub Pages or enables crawler.

Usage (only with dedicated production D1 credentials):
    python d1_migrate.py
An existing verified checkpoint is never overwritten. Partial imports can be
rerun: document upserts are idempotent and only the final verified import writes
the crawler checkpoint.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from d1_preflight import pack, dt
from d1_store import D1Store


def source_records(source, cutoff):
    selected = []
    expected = {}
    old = 0
    for row in source.get("items", []):
        published = dt(row.get("datum_zverejneni")) or dt(row.get("datum_zalozeni"))
        if published is None:
            raise RuntimeError("Source has an undated record; migration stopped")
        if published < cutoff:
            old += 1
            continue
        rid = int(row["id"])
        if rid in expected:
            raise RuntimeError("Duplicate source ID; migration stopped")
        payload, digest = pack(row)
        if len(payload) > 1_800_000:
            raise RuntimeError("Source has a row that exceeds D1 record limit")
        selected.append(row)
        expected[rid] = digest
    if not selected:
        raise RuntimeError("Source has no records inside retention window")
    return selected, expected, old


def migrate(store, source, state, now):
    if store.get_state() is not None:
        raise RuntimeError("D1 already has a crawler checkpoint. Refusing to overwrite it.")
    cutoff = now - timedelta(days=90)
    selected, expected, old = source_records(source, cutoff)
    print(f"Import source: {len(selected)} records, {old} past retention cutoff", flush=True)
    for start in range(0, len(selected), 500):
        store.upsert_documents(selected[start:start + 500])
        print(f"D1 import progress: {min(start + 500, len(selected))}/{len(selected)}", flush=True)
    verified = store.verify_import(expected)
    print(f"Verified all {verified} records against source SHA-256 checksums", flush=True)

    # This is the only checkpoint publication. Until it succeeds, crawler must
    # refuse to start. In particular, partial migrations cannot advance the cursor.
    store.query(
        "INSERT INTO isir_meta (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("migration_info", json.dumps({
            "source_updated_at": source.get("updated_at"),
            "migrated_at": now.isoformat(),
            "verified_records": verified,
            "expired_source_records": old,
            "retention_days": 90,
        }, sort_keys=True)),
    )
    store.save_state(state)
    print("Migration committed: checkpoint published, crawler still disabled", flush=True)


def main():
    root = Path(__file__).resolve().parent
    source = json.loads((root / "docs/results.json").read_text(encoding="utf-8"))
    state = json.loads((root / "data/state.json").read_text(encoding="utf-8"))
    if not state.get("current_id") or not state.get("all_documents_from_id"):
        raise RuntimeError("Legacy source checkpoint is incomplete")
    store = D1Store()  # defaults to exact database name isir-prod, never isir-test
    store.create_schema()
    migrate(store, source, state, datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
