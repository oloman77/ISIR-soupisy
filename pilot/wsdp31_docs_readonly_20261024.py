"""One-off inspection of public ČÚZK WSDP 3.1 technical documentation ZIP.

GETs precisely one official public ZIP, no WSDP authentication, no production
requests, no fake owner queries. Only logs operation names and documentation
excerpts relevant to inputs / geography / costs / negative results.
"""
import io,json,re,subprocess,tempfile,zipfile
from pathlib import Path
from urllib.request import Request,urlopen

URL="https://www.cuzk.gov.cz/Katastr-nemovitosti/Poskytovani-udaju-z-KN/Dalkovy-pristup/Webove-sluzby-dalkoveho-pristupu/WSDP_10_4_2026.aspx"
CAP=30_000_000

def main():
    req=Request(URL,headers={"User-Agent":"ISIR-Radar-Temporary-WSDP31-Docs-Review/1.0"})
    with urlopen(req,timeout=45) as r:
        if r.status!=200:raise RuntimeError("official docs unavailable")
        raw=r.read(CAP+1)
    if len(raw)>CAP or not zipfile.is_zipfile(io.BytesIO(raw)):
        raise RuntimeError("not bounded ZIP")
    z=zipfile.ZipFile(io.BytesIO(raw))
    filenames=[n for n in z.namelist() if not n.endswith("/") and not n.startswith("../")]
    print("OFFICIAL_WSDP31_ARCHIVE")
    print(json.dumps({"bytes":len(raw),"files":[{"name":n,"bytes":z.getinfo(n).file_size}
                   for n in filenames][:100]},ensure_ascii=False,indent=2))
    if len(filenames)>200: raise RuntimeError("Archive exceeded file count safety limit")
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        summary=[]
        relevant=re.compile(r"přehled\s+vlastnictv|evidenc[ei]\s+práv\s+pro\s+osob|(?:\b|_)osoba|rodn[eé]|datum\s+narozen|IČO|K[oó]d\s+okresu|okres|negativn[ií]|nen[ií]\s+evidov|nulov|účtov|cena|poplat|vyhled[aá]n[ií]\s+vlastn",re.I)
        for n in filenames:
            suffix=Path(n).suffix.lower()
            if suffix not in (".pdf",".wsdl",".xsd",".xml",".txt",".htm",".html"):continue
            if z.getinfo(n).file_size>14_000_000:continue
            try:
                data=z.read(n)
                if suffix==".pdf":
                    source=root/"doc.pdf";source.write_bytes(data)
                    result=subprocess.run(["pdftotext","-layout",str(source),"-"],
                                           capture_output=True,timeout=24)
                    txt=result.stdout.decode("utf-8","replace")
                else:
                    txt=data.decode("utf-8","replace")
                if not txt.strip():continue
                matches=[]
                for m in relevant.finditer(txt):
                    if len(matches)>=30:break
                    a=max(0,m.start()-130);b=min(len(txt),m.end()+320)
                    sample=re.sub(r"\s+"," ",txt[a:b])
                    if any(abs(m.start()-x[0])<180 for x in matches):continue
                    matches.append((m.start(),sample))
                summary.append({"file":n,"chars":len(txt),
                       "relevant_excerpt_count":len(matches),
                       "excerpts":[v for _,v in matches],
                       "tag_operations":sorted(set(re.findall(r'<(?:wsdl:)?operation\s+name=["\']([^"\']+)',txt)))[:100]})
            except Exception as exc:
                summary.append({"file":n,"error":type(exc).__name__})
        # Extract exact WSDP 3.1 request field trees from the OFFICIAL XSD.
        from xml.etree import ElementTree as ET
        targets=[
          n for n in filenames if n.endswith((
            "/sestavy_v3_1.xsd","/vyhledat_v3_1.xsd",
            "/baseTypes_v3_1.xsd"))]
        field_reports=[]
        for filename in targets:
            rootxml=ET.fromstring(z.read(filename))
            for el in rootxml.iter():
                name=el.attrib.get("name","")
                if not (name and any(x in name.casefold() for x in
                    ("generujprehledvlastnictvi","generujevidencipravproosobu",
                     "najdiosrequest","najdios","sestavybasetype",
                     "typopravnenehosubjektu","rctype"))):
                    continue
                if not (name.endswith("RequestType") or name in
                    ("SestavyBaseType","TypOpravnenehoSubjektuSestavyType","RcType")):
                    continue
                fields=[]
                for child in el.iter():
                    if child is el:continue
                    tag=child.tag.rsplit("}",1)[-1]
                    if tag not in ("element","group","choice","sequence","attribute"):continue
                    fields.append({"tag":tag,"name":child.attrib.get("name"),
                        "ref":child.attrib.get("ref"),"type":child.attrib.get("type"),
                        "min":child.attrib.get("minOccurs")})
                field_reports.append({"file":filename.split("/")[-1],
                    "request_type":name,"fields":fields[:65]})
        print("OFFICIAL_WSDP31_EXACT_REQUEST_FIELDS")
        print(json.dumps(field_reports,ensure_ascii=False,indent=2))
        print("OFFICIAL_WSDP31_STRUCTURE_AND_TERMS")
        print(json.dumps([x for x in summary if "/ws3_1/wsdp/" in x["file"]],ensure_ascii=False,indent=2))
if __name__=="__main__":main()
