"""Region evidence in documents, not a confirmation of ownership."""
import re
import unicodedata

REGIONS = ("Hlavní město Praha", "Středočeský kraj", "Jihočeský kraj",
           "Plzeňský kraj", "Karlovarský kraj", "Ústecký kraj",
           "Liberecký kraj", "Královéhradecký kraj", "Pardubický kraj",
           "Kraj Vysočina", "Jihomoravský kraj", "Olomoucký kraj",
           "Moravskoslezský kraj", "Zlínský kraj")

def norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c)).lower()).strip()

def extract_regions(text, records=()):
    t = norm(text)
    found = []
    def add(region, method, evidence, record=None):
        item = {"kraj": region, "metoda": method, "doklad": evidence}
        if record:
            item.update({k: record.get(k, "") for k in
                         ("ku_kod", "ku_nazev", "obec", "pracoviste")})
        if item not in found:
            found.append(item)
    prefix = r"\bkatastraln(?:i|im|iho)\s+urad(?:em|u)?\s+pro\s+"
    for region in REGIONS:
        alias = norm(region)
        if region == "Hlavní město Praha":
            alias = r"(?:hlavni mesto prahu|hl\.\s*m\.\s*prahu)"
        elif region == "Kraj Vysočina":
            alias = r"(?:vysocinu|kraj vysocina)"
        for m in re.finditer(prefix + alias + r"\b", t):
            add(region, "nazev_uradu", m.group())
    # Only consider text explicitly labelled as a cadastral territory.
    label = r"(?:\bkatastralni(?:ho|m)?\s+uzemi|\bk\.\s*u\.)\s*[:\-]?\s*"
    by_code = {r["ku_kod"]: r for r in records}
    by_name = {}
    for record in records:
        by_name.setdefault(norm(record["ku_nazev"]), []).append(record)
    names = sorted(by_name, key=len, reverse=True)
    for m in re.finditer(label, t):
        tail = t[m.end():m.end()+130]
        code_match = re.match(r"(?:kod\s*)?\[?(\d{6})\b", tail)
        candidates = []
        evidence = m.group()
        if code_match:
            record = by_code.get(code_match[1])
            candidates = [record] if record else []
            evidence += code_match.group()
        else:
            for name in names:
                if tail.startswith(name) and (len(tail) == len(name) or not tail[len(name)].isalnum()):
                    candidates = by_name[name]
                    evidence += name
                    after = tail[len(name):]
                    code_match = re.match(r"\s*\[\s*(\d{6})\s*\]", after)
                    if code_match:
                        candidates = [r for r in candidates if r["ku_kod"] == code_match[1]]
                        evidence += code_match.group()
                    break
        # Ambiguous names are not guessed.
        if len(candidates) == 1:
            r = candidates[0]
            add(r["kraj"], "kod_ku" if code_match else "nazev_ku", evidence, r)
    return found

