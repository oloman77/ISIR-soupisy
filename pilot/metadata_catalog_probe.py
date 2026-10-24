"""One-time read-only inspection of public official ISIR XLS column layout.

No SOAP, PDF, D1, private data, crawler or external providers.
"""
from urllib.request import Request,urlopen
import json
from pilot.metadata_7d_live import CATALOG,normalize

def main():
    import xlrd
    req=Request(CATALOG,headers={"User-Agent":"ISIR-Radar-Metadata-Catalog-Probe/1.0"})
    with urlopen(req,timeout=35) as response:
        data=response.read(6_000_001)
    if len(data)>6_000_000 or not data.startswith(bytes.fromhex("d0cf11e0")):
        raise RuntimeError("Invalid official XLS")
    workbook=xlrd.open_workbook(file_contents=data)
    sh=workbook.sheet_by_index(0)
    rows=[]
    matches=[]
    for i in range(min(sh.nrows,1500)):
        values=[str(sh.cell_value(i,c)).strip()[:150] for c in range(min(sh.ncols,5))]
        if i<12:rows.append([i,values])
        if any(word in normalize(" ".join(values)) for word in (
            "soupis","majetk","zpen","drazb","oprava","dopln")):
            if len(matches)<110:matches.append([i,values])
    print("OFFICIAL ISIR CATALOG XLS STRUCTURAL PROBE; GET ONLY")
    print(json.dumps({"sheet":sh.name,"row_count":sh.nrows,
        "column_count":sh.ncols,"first_rows":rows,
        "matched_relevant_rows_capped":matches},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
