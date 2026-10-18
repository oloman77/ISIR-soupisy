"""One-time read-only probe of public insolvency sale index for a dependable feed.

No login, no private APIs, no Cloudflare access, no crawler deployment.
Reads one HTML page and at most three same-host JS assets, with byte limits.
Logs only URL paths/structural facts, never source data or credentials.
"""
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin
from urllib.request import Request,urlopen
import json
import re

HOST="www.portaldrazeb.cz"
ROOT="https://www.portaldrazeb.cz/insolvencni-zamery"
MAX_PAGE=1_500_000
MAX_SCRIPT=2_000_000

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts=[]
        self.links=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="script" and d.get("src"):self.scripts.append(d["src"])
        if tag=="a" and d.get("href"):self.links.append(d["href"])

def safe_url(url):
    z=urlsplit(url)
    return (z.scheme=="https" and z.hostname==HOST and z.port in (None,443)
            and not z.username and not z.password)

def fetch(url,cap):
    if not safe_url(url):raise ValueError("out-of-scope URL")
    req=Request(url,headers={"User-Agent":"ISIR-Radar-Safe-Discovery/0.1"})
    with urlopen(req,timeout=25) as response:
        if not safe_url(response.url): raise ValueError("external redirect")
        b=response.read(cap+1)
        if len(b)>cap:raise ValueError("response exceeded byte cap")
        return b.decode("utf-8","replace"),response.status,response.headers.get("Content-Type","")

def main():
    html,status,content_type=fetch(ROOT,MAX_PAGE)
    page=Page();page.feed(html)
    in_page_links=sorted({urljoin(ROOT,x) for x in page.links
                         if safe_url(urljoin(ROOT,x)) and
                         "/insolvencni-zamer/" in urljoin(ROOT,x)})
    index_static_count=len(in_page_links)
    report={
        "index_http_status":status,
        "index_content_type":content_type[:50],
        "index_has_rendered_listing_links":bool(in_page_links),
        "rendered_listing_link_count":index_static_count,
        "js_script_tags":len(page.scripts),
        "indexed_candidates_from_server_html":in_page_links[:5],
        "frontend_looks_dynamic":bool(re.search(r"\{\{\s*(?:auction|intention|intent|sale)\.",html)),
        "js_candidate_routes":[],
        "notes":"This is a read-only public-source feasibility probe, not an importer.",
    }
    # No broad crawling, only at most 3 same-host Javascript resources.
    paths=[urljoin(ROOT,x) for x in page.scripts]
    assets=[x for x in paths if safe_url(x) and x.endswith(".js") and
            ("app" in x or "main" in x or "insol" in x or "chunk" in x)]
    for path in assets[:3]:
        try:
            src,s,ct=fetch(path,MAX_SCRIPT)
            matches=set()
            patterns=[
                r"""(?:/api/|/public/)[A-Za-z0-9/_-]{3,80}""",
                r"""(?:/insolvency/|/insolvencni-zamer|/sale-intent|/intention)[A-Za-z0-9/_-]{0,80}""",
                r"""https://[A-Za-z0-9.-]+/(?:api|public)/[A-Za-z0-9/_-]{2,80}""",
            ]
            for p in patterns:
                matches.update(re.findall(p,src,re.I)[:12])
            report["js_candidate_routes"].append({
                "script_path":urlsplit(path).path[:120],
                "http_status":s,
                "possible_route_names":sorted(matches)[:25],
                "bytes_read":len(src.encode("utf-8")),
            })
        except Exception as e:
            report["js_candidate_routes"].append({
              "script_path":urlsplit(path).path[:120],
              "error_type":type(e).__name__
            })
    print("READ-ONLY SOURCE DISCOVERY (NO LOGIN/NO DATA IMPORT)")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
