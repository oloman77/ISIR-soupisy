"""Read-only analysis of legacy ISIR PDF property candidates and Radar D1.
Does not download PDFs, modify records, start or schedule the crawler.
Only logs public ISIR source identifiers/URLs; never logs private user decisions.
"""
from collections import Counter
import json
from radar.import_legacy import ROOT, TARGETS, candidates, inferred_location, normal, territories

def audit(source, mapping):
    rows=source.get("items",[])
    pdf=[r for r in rows if r.get("obsahuje_nemovitost") is True
         and r.get("pdf_status")=="ok" and r.get("dokument_url")]
    eligible=list(candidates(source,mapping))
    known=[(r,loc) for r,loc in eligible if loc[0] in TARGETS]
    unknown=[r for r,loc in eligible if not loc[0]]
    classes=Counter()
    available=Counter()
    sample=[]
    for r in unknown:
        ku=r.get("katastralni_uzemi") or []
        pairs=set()
        for n in ku:
            pairs.update(mapping.get(normal(n),set()))
        districts={p[0] for p in pairs}
        if not ku: reason="chybí vytěžené katastrální území"
        elif not pairs: reason="vytažené názvy KU neodpovídají číselníku"
        elif len(districts)>1: reason="konflikt více okresů"
        else: reason="jiný problém"
        classes[reason]+=1
        available["has_ku"]+=bool(ku)
        available["has_office"]+=bool(r.get("katastralni_pracoviste"))
        available["has_municipality"]+=bool(r.get("obce"))
        available["has_geographical_evidence"]+=bool(r.get("lokalita_doklady"))
        available["has_regions"]+=bool(r.get("kraje") or r.get("kraj"))
        available["has_pdf_last_attempt"]+=bool(r.get("pdf_last_attempt"))
        available["unique_cases_dummy"]+=0
        if len(sample)<12:
            sample.append({
                "id":r.get("id"),"spis":r.get("spisova_znacka"),
                "classification":reason,
                "ku":ku[:3],
                "kraje":(r.get("kraje") or [])[:3],
                "offices":(r.get("katastralni_pracoviste") or [])[:3],
                "obce":(r.get("obce") or [])[:3],
                "signal_count":len(r.get("nemovitost_signaly") or []),
                "lokalita_version":r.get("lokalita_version"),
            })
    available.pop("unique_cases_dummy",None)
    cases=Counter(str(r.get("spisova_znacka") or "").strip() for r in unknown)
    top=[]
    for r,loc in known:
        evidence=r.get("lokalita_doklady") or []
        top.append({
            "id":r.get("id"),"spis":r.get("spisova_znacka"),
            "source_event":str(r.get("popis_udalosti") or "")[:160],
            "district_suggestion":loc[0],"municipality_suggestion":loc[1],
            "ku":r.get("katastralni_uzemi") or [],
            "kraje":r.get("kraje") or [],
            "obce":r.get("obce") or [],
            "lokalita_doklady_count":len(evidence),
            "lokalita_doklady_sample":[{
                k:el.get(k) for k in ["ku_nazev","okres","kraj","obec","pracoviste"]
                if el.get(k)} for el in evidence[:4] if isinstance(el,dict)],
            "signals":(r.get("nemovitost_signaly") or [])[:8],
            "source_pdf_url":r.get("dokument_url"),
            "case_url":r.get("isir_rizeni_url") or r.get("isir_search_url") or "",
            "pdf_last_attempt":r.get("pdf_last_attempt"),
        })
    return {
      "snapshot_updated_at":source.get("updated_at"),
      "total_source_rows":len(rows),
      "confirmed_pdf_property_suspicions":len(pdf),
      "with_extracted_ku":sum(bool(r.get("katastralni_uzemi")) for r in pdf),
      "geographically_eligible_docs":len(eligible),
      "target_district_suggestions":len(known),
      "unknown_district_docs":len(unknown),
      "unknown_doc_cases":len(cases),
      "unknown_geographic_reason_counts":dict(classes),
      "unknown_available_metadata_counts":dict(available),
      "suggested_four":top,
      "unknown_examples":sample,
      "limitations":[
        "Neověřuje, zda PDF skutečně dokládá prodej či vlastnictví nemovitosti.",
        "Názvy katastrálních území v PDF mohou být jen vedlejší zmínkou.",
        "Dosud neanalyzované nebo chybové PDF se nepočítají mezi potvrzená podezření.",
        "Nejde o aktualizaci ISIR od data historického snapshotu."
      ],
    }

def main():
    source=json.loads((ROOT/"docs/results.json").read_text(encoding="utf-8"))
    mapping=territories()
    result=audit(source,mapping)
    try:
        from radar.initialize import resolve
        db=resolve()
        d1=db.query("SELECT id,title,district,municipality,location_confidence FROM properties WHERE id LIKE 'isir-doc:%' ORDER BY id")
        result["live_radar_record_count"]=len(d1)
        result["live_radar_record_ids"]=[p.get("id") for p in d1]
        result["live_radar_record_location_confidence"]={
            p["id"]:p.get("location_confidence") for p in d1}
        # No personal property_decisions or decision_history content is fetched.
    except (KeyError, RuntimeError) as e:
        result["live_radar_check_failed"]=type(e).__name__
        raise
    print("READ-ONLY ISIR RADAR LEGACY AUDIT (NO CRAWLER RUN)")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
