# ISIR Radar – první verze (Cloudflare Pages + D1)

Nový, **samostatný** portál vedle stávajícího starého crawleru. Záměrně
nezapíná současný crawler ani nevyžaduje dokončení PR #4.

## Co umí

- Soukromý webový přehled nemovitostí.
- Filtry: okres, stav, priorita, text, typ, zdroj, vlastní štítek.
- Ruční doplnění nemovitosti a odkazu na jiný zdroj.
- Detail: zdroje, poznámky, vlastní název, ručně opravený okres.
- Stavy: nová, sledovaná, k oslovení, nabídka odeslána, čekáme na prodej,
  odmítnutá, archivovaná, získaná.
- Vlastní štítky, priorita a datum další kontroly.
- Historie změn vlastního hodnocení.
- Import kandidátů z dosavadního ISIR results.json. **Import není crawler**.
- Vlastní rozhodnutí jsou v samostatné tabulce, kterou import nikdy nepřepisuje.

## Bezpečnost a přihlášení bez platební karty

Cloudflare Zero Trust **není potřeba**. Celé rozhraní i API chrání
`functions/_middleware.js` přes šifrované HTTPS a HTTP Basic Authentication.
Pro přihlášení používej uživatelské jméno `radar` a **vlastní, unikátní,
náhodné heslo dlouhé minimálně 11 znaků**. Při nevyplněném nebo příliš krátkém
hesle aplikace odmítne všechny požadavky (včetně statických souborů).

Cloudflare Dashboard → Workers & Pages → **isir-radar** → Settings →
**Variables and Secrets** → **Add**:

- Name: `RADAR_LOGIN_PASSWORD`
- Type: **Secret** (Encrypted)
- Value: náhodné heslo z password manageru, ideálně 16–24 znaků
- Environment: **Production**. Pro Preview totéž, jen pokud chceš
  používat náhledové verze; jinak je nechej uzamčené.
- Uložit a provést nové nasazení aplikace, aby se Secret načetl.

Heslo **nedávej do GitHubu, kódu ani do chatu**. Cloudflare ho uchová jako
Secret, server ho nikdy nevrací a v logu se neobjevuje. Webový prohlížeč zobrazí
standardní přihlašovací dialog (uživatel `radar`, heslo dle Secretu).
Doporučujeme správce hesel pro vyplňování na PC i telefonu.

**Omezení:** Je to jednouživatelská verze s jedním sdíleným heslem; nenabízí
individuální uživatelské účty ani jednorázové přihlášení. Při prozrazení
hesla ho změň v Cloudflare Secret a znovu nasaď. Server vyžaduje HTTPS,
blokuje cizí Origin u zápisů a u citlivých odpovědí zakazuje cache, ale
neobsahuje samostatné omezení počtu pokusů. Proto používej **silné, unikátní
generované heslo**, ne běžnou frázi.

## Nasazení přes GitHub Actions

1. Cloudflare D1: samostatná existující databáze `isir-radar`, jurisdikce
   EU. Databáze `isir-test` a `isir-prod` zůstávají nedotčené.
2. Cloudflare Pages `isir-radar` vytváří workflow `radar-pages.yml` jako
   Direct Upload přes Wrangler; po změně Radaru na `main` se nasadí automaticky.
3. GitHub Secrets:
   - `CLOUDFLARE_PAGES_API_TOKEN`: Cloudflare Pages Edit pro daný účet.
   - `CLOUDFLARE_API_TOKEN`: původní token s D1 oprávněním, zachovat.
   - `CLOUDFLARE_ACCOUNT_ID`: existující ID účtu.
4. `radar/cloudflare_deploy_setup.py` ověřuje databázi EU a D1 binding `DB`
   ve webu. Když binding existuje, nechává původní nastavení a Secrets nedotčené.
5. Ověřit přístup na `https://isir-radar.pages.dev/`. Bez Secretu musí být
   odpověď HTTP 503, s heslem standardní HTTP Basic dialog a při správném
   přihlášení vlastní přehled.
6. Stávající crawler se nijak neaktivuje a nerestartuje.


## Import stávajících nálezů z ISIR

V GitHub Repository Secrets vytvořit **nový** secret:
`CLOUDFLARE_RADAR_D1_DATABASE_ID` = UUID nové databáze.
Stávající `CLOUDFLARE_API_TOKEN` a `CLOUDFLARE_ACCOUNT_ID` se používají
pouze pro omezené jednorázové GitHub Actions spuštění; token musí mít právo
D1 Edit pro tuto novou databázi.

GitHub Actions -> **ISIR Radar – initialize D1 and import candidates** ->
Run workflow. Spouští se **jen ručně**. Workflow:
- Ověří, že D1 databáze se jmenuje `isir-radar`.
- Vytvoří tabulky z `radar/schema.sql`.
- Použije veřejný číselník ČÚZK pro předběžné určení okresů.
- Importuje dokumenty s rozpoznaným signálem nemovitosti; při neznámé
  lokalitě ponechá kandidáty, pokud okres není vyloučen.
- Vzdálené množství provizorních kandidátů zkontroluje dotazem do D1.
- Žádnou existující osobní poznámku nebo stav nepřepíše.

Pokud nemá kandidát jednoznačně odpovídající katastrální území, jeho okres
zůstane *Neurčeno*. Pokud PDF pouze zmiňuje cílové území, označení okresu je
stále **navržené, nikoli ověřené vlastnictví a poloha prodávaného majetku**.

## Co ještě není hotové

- Automatické monitorování webů jednotlivých správců, aukčních portálů,
  realitních serverů a dalších registrů.
- Automatické párování více dokumentů na jeden skutečný list vlastnictví
  nebo jednu nemovitost; první import vytváří **provizorní položku na PDF**.
- Analýza skutečných katastrálních identifikátorů / vlastnických podílů.
- Automatické hlídání změn stavu na jiných zdrojích, notifikace a plánované úkoly.
- Migrace původní provozní fronty crawleru – ta se řeší samostatně až po
  schválení nové selektivní strategie sběru.

**Nevypínejte ani nepřepisujte testovací `isir-test`. Neaktivujte původní
periodický crawler jen kvůli importu dat do portálu.**

## Technický přehled

- `radar/public/index.html` – český responzivní frontend
- `functions/_middleware.js` – ochrana heslem a CSRF kontrola (včetně statiky)
- `functions/api/properties.js` – filtrovaný katalog, ruční přidání
- `functions/api/property.js` – stabilní detailové API (`?id=...`) pro identifikátory obsahující dvojtečku
- `functions/api/properties/[id].js` – společná logika detailu a úprav hodnocení
- `radar/schema.sql` – normalizované tabulky
- `radar/import_legacy.py` – jednorázový import
- `test_radar.py` – lokální testy
