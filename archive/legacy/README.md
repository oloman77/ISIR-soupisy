# Archiv původního ISIR crawleru

Původní workflow `.github/workflows/isir.yml` bylo při přechodu na selektivní monitoring **vyřazeno z aktivních GitHub Actions** a uloženo zde jako [`isir.yml`](isir.yml) (24. 10. 2026).

## Co se změnilo

- Z aktivní složky `.github/workflows/` byla odebrána pouze stará automatizace: **žádný další půlhodinový běh**, žádné nové automatické stahování PDF, žádné přepisování starých výsledků z tohoto workflow.
- `crawler.py`, `regions.py`, `build_briefing.py`, `data/state.json`, `docs/results.json`, `docs/briefing.json` a stará GitHub Pages prezentace nebyly měněny.
- ISIR Radar na Cloudflare Pages, jeho D1 databáze, workflow a ruční hodnocení zůstaly nedotčeny.
- Jiné ručně spouštěné bezpečně ohraničené piloty zůstaly samostatné.

## Historický stav

Poslední dohledaný běh workflow `ISIR crawler + Pages` byl 18. 9. 2026, skončil chybou. Z historického běhu nelze spolehlivě usoudit, jaký byl před archivací přepínač Enabled/Disabled v UI GitHub Actions. Zdrojové workflow přesto obsahovalo aktivní definici harmonogramu `*/30 * * * *`.

## Obnova (jen po novém rozhodnutí)

Neobnovovat původní workflow prostým zkopírováním archivního souboru do `.github/workflows`. Vyžaduje:
1. Schválenou strategii a vyčíslenou kapacitu / počet potřebných dokumentů.
2. Vyhodnocení bezpečnosti a velikosti `docs/results.json`, současného `data/state.json`, naplánovaných běhů a práv GitHub Actions.
3. Nový izolovaný návrh s read-only pilotem, měřitelnými limity a jasným plánem návratu.
4. Ověření, že nejsou dotčeny `isir-radar` D1, soukromá rozhodnutí ani nové piloty.

Podrobnosti: [projektová znalostní báze](../../docs/PROJECT-KNOWLEDGE-BASE.md).
