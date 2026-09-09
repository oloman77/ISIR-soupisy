"""Read-only sample. Never writes crawler state or production results."""
import json
from pathlib import Path
import crawler as c
from regions import extract_regions

mp, _ = c.load_cuzk()
items = json.loads(Path('docs/results.json').read_text())['items']
items = [r for r in items if r.get('obsahuje_nemovitost') and r.get('dokument_url')]
# Half without a previously known region, half with one.
sample = [r for r in items if not r.get('kraj')][:5] + [r for r in items if r.get('kraj')][:5]
output = []
for row in sample:
    text, status = c.pdf_text(row['dokument_url'])
    evidence = extract_regions(text, mp.values()) if status == 'ok' else []
    result = dict(id=row['id'], url=row['dokument_url'], status=status,
                  old_region=row.get('kraj'), evidence=evidence)
    output.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
Path('region-pilot.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
assert sample, 'No sample documents available'
assert any(r['status']=='ok' for r in output), 'No PDF read successfully'
