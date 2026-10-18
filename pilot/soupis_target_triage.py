"""Read-only triage of 955-ish historic ISIR estate inventory candidates.

No PDF download, no crawler, no Cloudflare/DB. Rank only existing official
metadata for target districts Kutna Hora / Havlickuv Brod. Explicitly distinguish
a proven cadastral *mention* from an asset belonging to the insolvency estate.
"""
from collections import Counter
import json

from pilot.soupis_documents import SOURCE, category, safe_pdf_url
from radar.import_legacy import TARGETS, TARGET_REGIONS, inferred_location, normal, territories

def triage(source,mapping):
    candidates=[]
    counts=Counter()
    for row in source.get("items",[]):
        if category(row)!="soupis_candidate":continue
        try:safe_pdf_url(row.get("dokument_url"))
        except (ValueError,TypeError):continue
        counts["soupis_metadata_pdf_links"]+=1
        ku=row.get("katastralni_uzemi") or []
        matches=set()
        for name in ku:
            matches.update(mapping.get(normal(name),set()))
        districts={d for d,m in matches}
        mapped_district,mapped_municipality,_=inferred_location(row,mapping)
        regions=set(row.get("kraje") or [])
        if row.get("kraj"):regions.add(row["kraj"])
        target_mentions=sorted(districts & TARGETS)
        if target_mentions:
            group="target_cadastral_mention"
        elif districts:
            group="other_district_cadastral_mentions"
        elif regions & TARGET_REGIONS:
            group="target_region_mention_only"
        elif regions:
            group="other_region_only"
        else:
            group="no_geographic_metadata"
        counts[group]+=1
        if len(districts)>1:counts["conflicting_district_mentions"]+=1
        if ku:counts["any_extracted_cadastral_name"]+=1
        if group not in ("target_cadastral_mention","target_region_mention_only"):
            continue
        candidates.append({
           "source_id":str(row["id"]),
           "case_reference":str(row.get("spisova_znacka") or "")[:50],
           "event_title":str(row.get("popis_udalosti") or "")[:120],
           "group":group,
           "cadastral_names":ku[:12],
           "matching_districts":sorted(districts),
           "matching_target_districts":target_mentions,
           "municipality_suggestion":mapped_municipality if mapped_district in TARGETS else "",
           "target_regions_mentioned":sorted(regions & TARGET_REGIONS),
           "pdf_status_from_archive":row.get("pdf_status"),
           "asset_in_estate_verified":False,
        })
    return {
       "snapshot_updated_at":source.get("updated_at"),
       "selection_counts":dict(counts),
       "target_cadastral_document_leads":[r for r in candidates
          if r["group"]=="target_cadastral_mention"][:60],
       "target_region_only_document_leads":[r for r in candidates
          if r["group"]=="target_region_mention_only"][:30],
       "target_only_is_a_mention":True,
       "no_database_writes":True,
       "old_crawler_started":False,
       "notes":[
         "ISIR event metadata does not confirm actual inventory status.",
         "Document cadastral names may be collateral, references or third-party properties.",
         "A region alone never confirms Kutna Hora or Havlickuv Brod district.",
         "No PDF OCR/read is performed, so unknown geography remains unknown."
       ]
    }

def main():
    source=json.loads(SOURCE.read_text(encoding="utf-8"))
    result=triage(source,territories())
    print("READ-ONLY TARGET TRIAGE OF HISTORIC SOUPIS DOCUMENTS")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
