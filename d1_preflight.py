"""Bounded D1 migration rehearsal. Does not modify crawler files or deploy Pages."""
import base64
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path


def pack(row):
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(zlib.compress(raw)).decode(), hashlib.sha256(raw).hexdigest()


def dt(value):
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class D1:
    def __init__(self):
        names = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_D1_DATABASE_ID")
        missing = [name for name in names if not os.environ.get(name, "").strip()]
        if missing:
            raise RuntimeError("Missing GitHub Secrets: " + ", ".join(missing))
        token, account, database = [os.environ[name].strip() for name in names]
        if not re.fullmatch(r"[a-f0-9]{32}", account) or not re.fullmatch(r"[a-f0-9-]{36}", database):
            raise RuntimeError("Account ID or database ID has invalid format")
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}"
        self.token = token
        self.read = self.written = self.size = 0

    def request(self, suffix="", data=None):
        request = urllib.request.Request(
            self.url + suffix,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            # Never print response bodies, request headers, token, or request URLs.
            try:
                codes = [str(x.get("code")) for x in json.loads(error.read()).get("errors", [])]
            except (ValueError, TypeError):
                codes = []
            raise RuntimeError(f"Cloudflare HTTP {error.code}; error codes: {','.join(codes)}. Check D1 Edit permission and account/database IDs.") from None
        except urllib.error.URLError:
            raise RuntimeError("Cloudflare connection failed; rerun the preflight") from None
        if not body.get("success"):
            codes = [str(x.get("code")) for x in body.get("errors", [])]
            raise RuntimeError("Cloudflare rejected request; codes: " + ",".join(codes))
        return body["result"]

    def query(self, sql, params=()):
        result = self.request("/query", {"sql": sql, "params": list(params)})
        for part in result:
            if not part.get("success"):
                raise RuntimeError("D1 SQL operation failed")
            meta = part.get("meta", {})
            self.read += meta.get("rows_read", 0)
            self.written += meta.get("rows_written", 0)
            self.size = max(self.size, meta.get("size_after", 0))
        return result[0].get("results", [])


def main():
    cloud = D1()
    if cloud.request().get("name") != "isir-test":
        raise RuntimeError("Refusing rehearsal: target database must be named isir-test")
    if cloud.query("SELECT 1 AS ok")[0]["ok"] != 1:
        raise RuntimeError("D1 read test failed")
    print("D1 connection and read access verified", flush=True)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=90)
    source = json.loads(Path("docs/results.json").read_text())
    records = []
    old = invalid = candidates = pending = resume = 0
    daily = {}
    for row in source["items"]:
        published = dt(row.get("datum_zverejneni")) or dt(row.get("datum_zalozeni"))
        if published is None:
            invalid += 1
            continue
        if published < cutoff:
            old += 1
            continue
        payload, digest = pack(row)
        if len(payload) > 1_800_000:
            raise RuntimeError("A compressed record needs separate chunk storage before D1 migration")
        candidate = int(row.get("obsahuje_nemovitost") is True and row.get("pdf_status") == "ok" and bool(row.get("dokument_url")))
        todo = int(bool(row.get("dokument_url")) and (
            not row.get("pdf_checked") or row.get("pdf_status") != "ok"
            or int(row.get("enrichment_version") or 0) < 10
            or (row.get("obsahuje_nemovitost") is True and int(row.get("lokalita_version") or 0) < 1)))
        records.append((int(row["id"]), published.isoformat(), candidate, todo, payload, digest))
        candidates += candidate
        pending += todo
        resume += bool(row.get("pdf_resume_text"))
        daily[published.date().isoformat()] = daily.get(published.date().isoformat(), 0) + 1
    if not records or len({row[0] for row in records}) != len(records):
        raise RuntimeError("Source is empty or has duplicate IDs")
    schema = "(id INTEGER PRIMARY KEY, published TEXT NOT NULL, candidate INTEGER NOT NULL, pending INTEGER NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL)"
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "rehearsal.sqlite"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE documents " + schema)
        db.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?)", records)
        db.execute("CREATE INDEX documents_date ON documents(published)")
        db.execute("CREATE INDEX documents_queue ON documents(pending,id)")
        db.execute("CREATE INDEX documents_candidates ON documents(candidate,id)")
        db.commit()
        for row in db.execute("SELECT payload,digest FROM documents"):
            raw = zlib.decompress(base64.b64decode(row[0]))
            if hashlib.sha256(raw).hexdigest() != row[1]:
                raise RuntimeError("Local roundtrip failed")
        local_bytes = path.stat().st_size
        db.close()
    # Fixed, dedicated rehearsal table; upserts allow interrupted tests to resume.
    cloud.query("CREATE TABLE IF NOT EXISTS isir_preflight_v1 " + schema)
    # Include the largest payloads and a spread of dates/states.
    chosen = {row[0]: row for row in sorted(records, key=lambda x: len(x[4]), reverse=True)[:100]}
    stride = max(1, len(records) // 900)
    for row in records[::stride]:
        if len(chosen) >= 1000:
            break
        chosen[row[0]] = row
    sample = sorted(chosen.values())
    before = cloud.written
    for offset in range(0, len(sample), 10):
        batch = sample[offset:offset + 10]
        cloud.query("INSERT INTO isir_preflight_v1 VALUES " + ",".join(["(?,?,?,?,?,?)"] * len(batch))
                    + " ON CONFLICT(id) DO UPDATE SET published=excluded.published,candidate=excluded.candidate,pending=excluded.pending,payload=excluded.payload,digest=excluded.digest WHERE digest<>excluded.digest",
                    [value for row in batch for value in row])
    first_writes = cloud.written - before
    for offset in range(0, len(sample), 10):
        expected = {row[0]: row for row in sample[offset:offset + 10]}
        retrieved = cloud.query("SELECT * FROM isir_preflight_v1 WHERE id IN (" + ",".join("?" for _ in expected) + ")", list(expected))
        if len(retrieved) != len(expected):
            raise RuntimeError("D1 roundtrip missing records")
        for row in retrieved:
            original = expected[row["id"]]
            if (row["published"],row["candidate"],row["pending"],row["payload"],row["digest"]) != original[1:]:
                raise RuntimeError("D1 roundtrip mismatch")
            if hashlib.sha256(zlib.decompress(base64.b64decode(row["payload"]))).hexdigest() != original[5]:
                raise RuntimeError("D1 checksum mismatch")
    probe = sample[0]
    before = cloud.written
    cloud.query("INSERT INTO isir_preflight_v1 VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,digest=excluded.digest WHERE digest<>excluded.digest", probe)
    unchanged_writes = cloud.written - before
    report = {
        "source_updated_at": source.get("updated_at"), "tested_at": now.isoformat(),
        "days_back": 90, "retained_records": len(records), "expired_records": old,
        "invalid_date_records": invalid, "candidates": candidates, "pending": pending,
        "ocr_resume_records": resume, "local_full_sqlite_with_indexes_bytes": local_bytes,
        "largest_compressed_record_bytes": max(len(x[4]) for x in records),
        "d1_roundtrip_records": len(sample), "d1_sample_writes": first_writes,
        "d1_unchanged_upsert_writes": unchanged_writes,
        "d1_total_rows_read": cloud.read, "d1_total_rows_written": cloud.written,
        "d1_size_after_bytes": cloud.size,
        "top_daily_document_counts": sorted(daily.items(), key=lambda x: x[1], reverse=True)[:7],
        "production_changed": False,
        "note": "Full size is a local SQLite estimate; remote test is bounded to 1000 rows. Daily indexed-write budget still requires production workload measurement."
    }
    Path("d1-preflight-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
    if invalid or local_bytes > 250_000_000 or unchanged_writes:
        raise RuntimeError("Capacity or integrity gate needs review; see report")
    print("PREFLIGHT PASSED: remote sample preserved; production not switched", flush=True)


if __name__ == "__main__":
    main()
