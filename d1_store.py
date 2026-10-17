"""Cloudflare D1 persistence for ISIR. No repository JSON is used as a database.

The migration is explicit and separate. The live crawler refuses to start until
a fully verified checkpoint exists in the production database.
"""
import base64
import hashlib
import json
import os
import time
import zlib
from datetime import timezone

from d1_preflight import D1, dt, pack

CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS isir_documents (
    id INTEGER PRIMARY KEY,
    published TEXT NOT NULL,
    candidate INTEGER NOT NULL,
    pending INTEGER NOT NULL,
    payload TEXT NOT NULL,
    digest TEXT NOT NULL
)
"""
CREATE_META = """
CREATE TABLE IF NOT EXISTS isir_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS isir_documents_published ON isir_documents(published,id)",
    "CREATE INDEX IF NOT EXISTS isir_documents_queue ON isir_documents(pending,id)",
    "CREATE INDEX IF NOT EXISTS isir_documents_candidates ON isir_documents(candidate,published)",
)
UPSERT = (
    "INSERT INTO isir_documents (id,published,candidate,pending,payload,digest) VALUES "
    + "{values} "
    + "ON CONFLICT(id) DO UPDATE SET "
    + "published=excluded.published,candidate=excluded.candidate,"
    + "pending=excluded.pending,payload=excluded.payload,digest=excluded.digest "
    + "WHERE isir_documents.digest<>excluded.digest OR isir_documents.published<>excluded.published"
)
PUBLIC_FIELDS = (
    "id", "datum_zverejneni", "datum_zalozeni", "spisova_znacka",
    "typ_udalosti", "popis_udalosti", "dokument_url",
    "obsahuje_nemovitost", "pdf_checked", "pdf_status",
    "nemovitost_signaly", "kraj", "kraje", "obce",
    "katastralni_uzemi", "katastralni_pracoviste",
    "lokalita_doklady", "isir_rizeni_url", "isir_search_url",
)


def published_date(row):
    value = dt(row.get("datum_zverejneni")) or dt(row.get("datum_zalozeni"))
    if value is None:
        raise ValueError("Document has no valid publication date")
    return value.astimezone(timezone.utc).isoformat()


def document_flags(row):
    url = bool(row.get("dokument_url"))
    success = row.get("pdf_status") == "ok" and row.get("pdf_checked") is True
    candidate = bool(success and url and row.get("obsahuje_nemovitost") is True)
    needs_analysis = (not row.get("pdf_checked") or row.get("pdf_status") != "ok"
                      or int(row.get("enrichment_version") or 0) < 10)
    needs_location = (row.get("obsahuje_nemovitost") is True
                      and int(row.get("lokalita_version") or 0) < 1)
    return int(candidate), int(url and (needs_analysis or needs_location))


def public_candidate(row):
    return {k: row[k] for k in PUBLIC_FIELDS if k in row and row[k] not in (None, "", [], {})}


def unpack(payload, digest):
    raw = zlib.decompress(base64.b64decode(payload, validate=True))
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError("D1 document checksum mismatch")
    return json.loads(raw)


class D1Store:
    def __init__(self, cloud=None, expected_name=None):
        self.cloud = cloud if cloud is not None else D1()
        required = expected_name or os.environ.get("ISIR_D1_REQUIRED_NAME", "isir-prod")
        actual = self.cloud.request().get("name")
        if actual != required:
            raise RuntimeError(
                "D1 target mismatch: refusing to access a database other than "
                + required + ". The test database must not be used for production."
            )

    def query(self, sql, params=()):
        # Cloudflare transient failure may happen mid-migration; inserts are idempotent.
        for attempt in range(4):
            try:
                return self.cloud.query(sql, params)
            except RuntimeError as exc:
                transient = any(marker in str(exc) for marker in
                                ("HTTP 429", "HTTP 500", "HTTP 502",
                                 "HTTP 503", "HTTP 504", "connection failed"))
                if not transient or attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    def create_schema(self):
        self.query(CREATE_DOCUMENTS)
        self.query(CREATE_META)
        for sql in CREATE_INDEXES:
            self.query(sql)

    def get_state(self):
        rows = self.query("SELECT value FROM isir_meta WHERE key = ?", ("crawler_state",))
        return json.loads(rows[0]["value"]) if rows else None

    def require_state(self):
        state = self.get_state()
        if state is None:
            raise RuntimeError("D1 has no verified crawler checkpoint; run migration first")
        return state

    def save_state(self, state):
        self.query(
            "INSERT INTO isir_meta (key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("crawler_state", json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
        )

    def document_tuple(self, row):
        payload, digest = pack(row)
        if len(payload) > 1_800_000:
            raise RuntimeError("Oversized D1 record; needs chunk storage before migration")
        candidate, pending = document_flags(row)
        return (int(row["id"]), published_date(row), candidate, pending, payload, digest)

    def upsert_documents(self, rows):
        """Write small bounded statements; interruption is safe to retry."""
        batch, total = [], 0
        def flush():
            if not batch:
                return
            sql = UPSERT.format(values=",".join(["(?,?,?,?,?,?)"] * len(batch)))
            self.query(sql, [value for record in batch for value in record])
        for row in rows:
            record = self.document_tuple(row)
            # Both parameter count and HTTP body size must remain bounded.
            if batch and (len(batch) >= 10 or total + len(record[4]) > 1_200_000):
                flush()
                batch, total = [], 0
            batch.append(record)
            total += len(record[4])
        flush()

    def load_documents(self, cutoff):
        cutoff_str = cutoff.astimezone(timezone.utc).isoformat()
        rows, after = {}, 0
        while True:
            batch = self.query(
                "SELECT id,payload,digest FROM isir_documents "
                "WHERE published >= ? AND id > ? ORDER BY id LIMIT 200",
                (cutoff_str, after),
            )
            if not batch:
                break
            for item in batch:
                row = unpack(item["payload"], item["digest"])
                if int(row["id"]) != int(item["id"]):
                    raise RuntimeError("D1 ID mismatch")
                rows[str(item["id"])] = row
            after = int(batch[-1]["id"])
            if len(batch) < 200:
                break
        return rows

    def verify_import(self, expected):
        """Full remote ID/digest comparison; no checkpoint if anything differs."""
        after, seen = 0, 0
        while True:
            batch = self.query(
                "SELECT id,digest FROM isir_documents WHERE id > ? ORDER BY id LIMIT 1000",
                (after,),
            )
            if not batch:
                break
            for record in batch:
                rid = int(record["id"])
                if rid not in expected or expected[rid] != record["digest"]:
                    raise RuntimeError("Remote D1 migration ID or checksum differs from source")
                seen += 1
            after = int(batch[-1]["id"])
            if len(batch) < 1000:
                break
        if seen != len(expected):
            raise RuntimeError(f"Migration incomplete: D1 has {seen}, expected {len(expected)}")
        return seen

    def prune_expired(self, cutoff):
        self.query(
            "DELETE FROM isir_documents WHERE published < ?",
            (cutoff.astimezone(timezone.utc).isoformat(),),
        )
