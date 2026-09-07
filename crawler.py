import io, csv, json, os, re, time, zipfile, unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from pypdf import PdfReader

SERVICE_URL="https://isir.justice.cz:8443/isir_public_ws/IsirWsPublicService"
CUZK_KU_URL="https://services.cuzk.cz/sestavy/cis/SC_SEZNAMKUKRA_DOTAZ.zip"
ROOT=Path(__file__).resolve().parent
STATE_FILE=ROOT/"data/state.json"
RESULTS_FILE=ROOT/"docs/results.json"
DAYS_BACK=int(os.getenv("DAYS_BACK","30"))
MAX_BATCHES=int(os.getenv("MAX_BATCHES","1500"))
PAUSE=float(os.getenv("PAUSE","0.10"))

SOUPIS_RX=re.compile(r"(soupis.{0,50}majetkov[ée].{0,30}podstat|dopln[eě]n[ií].{0,50}soupis|aktualizovan[ýá].{0,50}soupis|zm[eě]na.{0,50}soupis|dodatek.{0,50}soupis|soupis\\s+majetku)",re.I|re.S)
REAL_PATTERNS=[r"katastr[aá]ln[ií]\\s+[úu]zem[ií]",r"list\\s+vlastnictv[ií]",r"\\bLV\\s*(?:č\\.?|číslo)?\\s*\\d+",r"parc(?:ela|ely|\\.?)\\s*(?:č\\.?|číslo)?\\s*[\\d/]+",r"\\bpozemek\\b",r"\\bstavba\\b",r"\\bjednotka\\b",r"\\bbyt\\b",r"rodinn[ýy]\\s+d[ůu]m",r"\\bnemovitost",r"\\bgar[aá][žz]\\b"]
KU_RX=[
 re.compile(r"katastr[aá]ln[ií]\\s+[úu]zem[ií]\\s*[:\\-]?\\s*([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][A-Za-zÁ-ž0-9 .'\\-]{1,70})",re.I),
 re.compile(r"\\bk\\.\\s*[úu]\\.\\s*[:\\-]?\\s*([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][A-Za-zÁ-ž0-9 .'\\-]{1,70})",re.I)
]

def lname(tag): return tag.split("}",1)[-1]
def find_text(el,name):
    for ch in el.iter():
        if lname(ch.tag)==name:return (ch.text or "").strip()
    return ""
def parse_dt(s):
    if not s:return None
    if s.endswith("Z"):s=s[:-1]+"+00:00"
    try:
        d=datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except:return None
def soap(body,timeout=90):
    env='<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:typ="http://isirpublicws.cca.cz/types/"><soapenv:Header/><soapenv:Body>'+body+'</soapenv:Body></soapenv:Envelope>'
    r=requests.post(SERVICE_URL,data=env.encode(),headers={"Content-Type":"text/xml; charset=utf-8","SOAPAction":""},timeout=timeout)
    r.raise_for_status(); return ET.fromstring(r.content)
def get_last_id():
    root=soap("<typ:getIsirWsPublicPosledniIdDataRequest/>")
    for el in root.iter():
        if lname(el.tag)=="cisloPosledniId":return int((el.text or "0").strip())
    raise RuntimeError("ISIR nevrátil poslední ID")
def get_after_id(i):
    root=soap(f"<typ:getIsirWsPublicIdDataRequest><idPodnetu>{int(i)}</idPodnetu></typ:getIsirWsPublicIdDataRequest>")
    rows=[]
    for el in root.iter():
        if lname(el.tag)!="data":continue
        rid=find_text(el,"id")
        if not rid.isdigit():continue
        rows.append({"id":int(rid),"datum_zverejneni":find_text(el,"datumZverejneniUdalosti"),"datum_zalozeni":find_text(el,"datumZalozeniUdalosti"),"spisova_znacka":find_text(el,"spisovaZnacka"),"typ_udalosti":find_text(el,"typUdalosti"),"popis_udalosti":find_text(el,"popisUdalosti"),"poznamka":find_text(el,"poznamka"),"dokument_url":find_text(el,"dokumentUrl")})
    return sorted(rows,key=lambda x:x["id"])
def is_soupis(r): return bool(SOUPIS_RX.search((r.get("popis_udalosti") or "")+"\n"+(r.get("poznamka") or "")))
def load_json(p,d):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except:return d
def save_json(p,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding="utf-8")
def locate_cutoff_id(cutoff,latest):
    lo,hi,best=0,latest,0
    for _ in range(28):
        if lo>hi:break
        mid=(lo+hi)//2;rows=get_after_id(mid)
        if not rows:hi=mid-1;continue
        dt=parse_dt(rows[0]["datum_zverejneni"]) or parse_dt(rows[0]["datum_zalozeni"])
        if not dt:hi=mid-1;continue
        if dt<cutoff:best=rows[0]["id"];lo=mid+1
        else:hi=mid-1
        time.sleep(PAUSE)
    return max(0,best-2000)
def norm(s):
    s=unicodedata.normalize("NFKD",s or "")
    s="".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\\s+"," ",re.sub(r"[^a-z0-9]+"," ",s)).strip()
def load_cuzk():
    r=requests.get(CUZK_KU_URL,timeout=60);r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name=[n for n in z.namelist() if n.lower().endswith(".csv")][0]
        raw=z.read(name)
    text=None
    for enc in ("cp1250","utf-8-sig","utf-8","latin1"):
        try:text=raw.decode(enc);break
        except:pass
    delim=";" if text[:10000].count(";")>=text[:10000].count(",") else ","
    mp={}
    for row in csv.DictReader(io.StringIO(text),delimiter=delim):
        ku=(row.get("KU_NAZEV") or "").strip(); office=(row.get("PRARES_NAZEV") or "").strip()
        if ku and office:
            mp[norm(ku)]={"ku_nazev":ku,"ku_kod":(row.get("KU_KOD") or "").strip(),"obec":(row.get("OBEC_NAZEV") or "").strip(),"pracoviste":office,"pracoviste_kod":(row.get("PRARES_KOD") or "").strip()}
    print(f"ČÚZK: načteno {len(mp)} katastrálních území",flush=True)
    return mp
def pdf_text(url):
    if not url:return "","no_url"
    try:
        r=requests.get(url,timeout=45);r.raise_for_status()
        if "pdf" not in (r.headers.get("content-type") or "").lower() and not r.content.startswith(b"%PDF"):return "","not_pdf"
        reader=PdfReader(io.BytesIO(r.content))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:40]),"ok"
    except Exception as e:return "","error:"+type(e).__name__
def detect_real(text):
    hits=[]
    for pat in REAL_PATTERNS:
        m=re.search(pat,text or "",re.I)
        if m:hits.append(m.group(0))
    uniq=[];seen=set()
    for h in hits:
        k=norm(h)
        if k not in seen:seen.add(k);uniq.append(h)
    return len(uniq)>=2,uniq[:8]
def extract_ku(text,mp):
    found={}
    for rx in KU_RX:
        for m in rx.finditer(text or ""):
            cand=re.split(r"[,;\n\r\(\)]",m.group(1),maxsplit=1)[0].strip(" .:-")
            n=norm(cand)
            if n in mp:found[n]=mp[n]
    return list(found.values())
def enrich(row,mp):
    text,status=pdf_text(row.get("dokument_url"))
    yes,hits=detect_real(text); infos=extract_ku(text,mp)
    row["pdf_checked"]=True;row["pdf_status"]=status;row["obsahuje_nemovitost"]=yes;row["nemovitost_signaly"]=hits
    row["katastralni_uzemi"]=sorted({x["ku_nazev"] for x in infos})
    row["obce"]=sorted({x["obec"] for x in infos if x["obec"]})
    row["katastralni_pracoviste"]=sorted({x["pracoviste"] for x in infos})
    return row
def main():
    now=datetime.now(timezone.utc);cutoff=now-timedelta(days=DAYS_BACK)
    state=load_json(STATE_FILE,{});old=load_json(RESULTS_FILE,{"items":[]})
    existing={str(x.get("id")):x for x in old.get("items",[]) if x.get("id") is not None}
    mp=load_cuzk();latest=get_last_id();current=state.get("current_id") or locate_cutoff_id(cutoff,latest)
    batches=processed=0
    while current<latest and batches<MAX_BATCHES:
        rows=get_after_id(current);batches+=1
        if not rows:break
        progressed=False
        for row in rows:
            if row["id"]<=current:continue
            progressed=True;current=max(current,row["id"]);processed+=1
            dt=parse_dt(row["datum_zverejneni"]) or parse_dt(row["datum_zalozeni"])
            if dt and dt>=cutoff and is_soupis(row):
                key=str(row["id"])
                if key in existing:
                    for k,v in existing[key].items():
                        if k not in row:row[k]=v
                existing[key]=row
        print(f"dávka {batches} | current={current} | processed={processed} | results={len(existing)}",flush=True)
        if not progressed:break
        time.sleep(PAUSE)
    valid=[];todo=[]
    for key,row in existing.items():
        dt=parse_dt(row.get("datum_zverejneni")) or parse_dt(row.get("datum_zalozeni"))
        if not(dt and dt>=cutoff):continue
        if "katastralni_pracoviste" not in row:todo.append((key,row))
        valid.append(row)
    print(f"PDF/KÚ k doplnění: {len(todo)}",flush=True)
    for i,(key,row) in enumerate(todo,1):
        existing[key]=enrich(row,mp)
        if i%25==0 or i==len(todo):print(f"PDF/KÚ zkontrolováno {i}/{len(todo)}",flush=True)
    valid=[]
    for row in existing.values():
        dt=parse_dt(row.get("datum_zverejneni")) or parse_dt(row.get("datum_zalozeni"))
        if dt and dt>=cutoff:valid.append(row)
    valid.sort(key=lambda r:parse_dt(r.get("datum_zverejneni")) or parse_dt(r.get("datum_zalozeni")) or datetime.min.replace(tzinfo=timezone.utc),reverse=True)
    offices=sorted({o for x in valid for o in (x.get("katastralni_pracoviste") or [])})
    save_json(STATE_FILE,{"current_id":current,"latest_id_at_run":latest,"last_run":now.isoformat(),"days_back":DAYS_BACK,"caught_up":current>=latest})
    save_json(RESULTS_FILE,{"updated_at":now.isoformat(),"days_back":DAYS_BACK,"current_id":current,"latest_id":latest,"caught_up":current>=latest,"count":len(valid),"count_real_estate":sum(1 for x in valid if x.get("obsahuje_nemovitost")),"katastralni_pracoviste_options":offices,"items":valid})
if __name__=="__main__":main()
