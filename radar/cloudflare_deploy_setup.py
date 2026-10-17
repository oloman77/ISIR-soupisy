"""Idempotent initial Cloudflare Pages provisioning for the isolated ISIR Radar.

Runs only from GitHub Actions with pre-existing Cloudflare API token. Never
changes the existing ISIR Pages project or the legacy crawler.
Requires Cloudflare Pages Write and D1 Read. No secret is logged.
"""
import json
import os
import urllib.error
import urllib.request

NAME = "isir-radar"
EXPECTED_JURISDICTION = "eu"

def api(method, url, data=None):
    token_name = "CLOUDFLARE_PAGES_API_TOKEN" if "/pages/" in url else "CLOUDFLARE_API_TOKEN"
    token = os.environ.get(token_name)
    if not token:
        raise RuntimeError(f"GitHub secret {token_name} is not configured")
    req = urllib.request.Request(
        url,
        data=(json.dumps(data).encode("utf-8") if data is not None else None),
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        # The HTTP status is enough for diagnosing missing permissions.
        # Do not echo an API error document since it may contain metadata.
        try:
            details = json.load(exc)
            errors = details.get("errors", [])
            safe_errors = [
                {"code": e.get("code"), "message": str(e.get("message", ""))[:160]}
                for e in errors[:3]
            ]
        except (ValueError, TypeError):
            safe_errors = []
        raise RuntimeError(
            f"Cloudflare {method} API rejected request: HTTP {exc.code}; "
            f"errors: {safe_errors}"
        ) from None
    if not payload.get("success"):
        raise RuntimeError(f"Cloudflare {method} API returned success=false")
    return payload["result"]


def configure():
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    base = f"https://api.cloudflare.com/client/v4/accounts/{account}"
    databases = api("GET", f"{base}/d1/database?name={NAME}")
    target = [db for db in databases if db.get("name") == NAME]
    if len(target) != 1:
        raise RuntimeError(f"Expected exactly one D1 database named {NAME}, got {len(target)}")
    database = target[0]
    if database.get("jurisdiction") != EXPECTED_JURISDICTION:
        raise RuntimeError(f"Refusing non-EU D1 jurisdiction for {NAME}")
    uuid = database["uuid"]
    print("Found Radar D1 with jurisdiction EU.")

    try:
        project = api("GET", f"{base}/pages/projects/{NAME}")
        print("Pages project already exists.")
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
        project = api("POST", f"{base}/pages/projects", {
            "name": NAME,
            "production_branch": "main",
        })
        print("Created new independent Pages project.")
    if project.get("name") != NAME:
        raise RuntimeError("Unexpected Pages project name")
    if project.get("source") and project["source"].get("type") in ("github", "gitlab"):
        raise RuntimeError("Existing project has a Git source. Refusing to replace it with direct upload.")

    # This is an isolated, new project. D1 binding is limited to its API runtime.
    project = api("PATCH", f"{base}/pages/projects/{NAME}", {
        "deployment_configs": {
            "production": {
                "d1_databases": {"DB": {"id": uuid}},
                "compatibility_date": "2026-10-01",
            },
            "preview": {
                "d1_databases": {"DB": {"id": uuid}},
                "compatibility_date": "2026-10-01",
            },
        }
    })
    if project.get("name") != NAME:
        raise RuntimeError("Pages patch returned an unexpected project")
    print("Configured dedicated D1 binding for the Radar Pages project.")

if __name__ == "__main__":
    configure()
