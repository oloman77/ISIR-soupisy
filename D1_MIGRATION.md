# ISIR → Cloudflare D1: řízená migrace (18. 10. 2026)

## Stav a bezpečnost

- Původní crawler zatím NEZAPÍNAT. Poslední běh 18. 9. 2026.
- Původní docs/results.json na main má přes 103 MB.
- Starý preflight prošel na testovací D1 databázi **isir-test**.
- Produkční migrace vyžaduje samostatnou databázi s přesným jménem **isir-prod**.
  Testovací DB se nepřepisuje a produkční kód ji výslovně odmítá.
- Import se spouští ručně, nevykonává crawler ani deploy.
- Crawler nenastartuje před úplně dokončeným importem s ověřeným checkpointem.
- Každý dokument má SHA-256 digest. Před vytvořením checkpointu se ověřují
  **všechny** importované ID a digesty proti vzdálené D1.
- Upserty lze po přerušení bezpečně zopakovat. Crawler ukládá dokumenty před
  posunem ISIR kurzoru.
- Na Pages se publikují pouze potvrzení kandidáti a statistiky, nikoli PDF
  fronta, OCR progres a retry metadata.

## Jednorázové nastavení

1. V účtu Cloudflare vytvořit novou D1 databázi pojmenovanou **isir-prod**.
   Testovací **isir-test** ponechat beze změn.
2. V GitHubu nastavit nový repository secret
   **CLOUDFLARE_D1_PROD_DATABASE_ID** na UUID produkční databáze.
   Stávající **CLOUDFLARE_API_TOKEN** a **CLOUDFLARE_ACCOUNT_ID** zachovat;
   token musí mít D1 Read/Write také pro produkční databázi.
3. Po úspěšných CI testech a revizi sloučit PR do main. Job workflow pro push
   neproběhne a cron podmínka vyžaduje zvláštní explicitní proměnnou.
4. Ručně spustit workflow **One-time D1 production migration**.
   Zkontrolovat počty, checksumy a závěrečné hlášení „Migration committed“.
   Pokud skončí neúplně, lze jej opakovat bez změny kurzoru.

## Ruční omezený test

1. Po importu ponechat repository variable **ISIR_SCHEDULE_ENABLED** nezadanou.
2. Je-li workflow ISIR crawler + Pages deaktivované, zapnout ho pro ruční
   spuštění. Cron stále zablokuje podmínka v jobu.
3. Spustit workflow manuálně s **max_batches=1**, **max_pdf_per_run=2**.
4. Ověřit D1 load i zápis, stránku, výsledný kompaktní JSON do 10 MB a
   že se nezměnil data/state.json.
5. Opakovat malý běh pro ověření persistence cursoru a retry stavu.
6. Teprve po ověření rozpočtu D1 a kapacity PDF fronty nastavit
   **ISIR_SCHEDULE_ENABLED=true**.

## Náklady a rizika

- V první migrační verzi crawler načítá celé 90denní okno z D1 při každém
  běhu. Je potřeba sledovat reálné rows_read, rows_written a dobu běhu;
  další evolucí má být stránkování jen aktivní fronty.
- Cloudflare D1 Workers Free má limit 5 milionů přečtených řádků a 100 tisíc
  zapsaných řádků denně. Plán po 30 minutách může tento limit vyčerpat.
- D1 Free má limit 500 MB na jednu databázi a 2 MB na řádek.
  Komprimované záznamy větší než 1,8 MB se nepovolí.
- Import přes REST API může narazit na globální rate limit; při přerušení
  lze idempotentní import zopakovat.
- Retence je 90 dní od spuštění importu (starší záznamy se vynechají).
- Dožene se mezera od zastavení 18. 9. 2026; původní nastavení 500 PDF za běh
  samo negarantuje, že se fronta nebude dál zvětšovat.

## Obnova

Při chybě migrace nevytvářet ručně checkpoint a nepřepínat crawler.
Při chybě běžného crawleru mezi zápisem dokumentů a checkpointu další běh
zopakuje idempotentní zápisy. Starý GitHub stav zůstává v historii.
