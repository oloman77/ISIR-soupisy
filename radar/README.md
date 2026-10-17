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

## Bezpečnost

Portál je **soukromý**. Middleware kontroluje kryptografický podpis
Cloudflare Access JWT, audience, issuer, expirační čas a povolenou e-mailovou
adresu. Bez nastavení přístupu nevrací ani statickou stránku.
V Cloudflare Zero Trust vytvořte Access Application chránící celý projekt
(ideálně včetně preview URL) a povolte jen svůj účet.

Nikdy nezveřejňujte tokeny, databázová hesla ani soukromé poznámky v GitHubu.
Pro sledování obchodních příležitostí doporučujeme Access chránit i při
případném přiřazení vlastní domény.

## Jednorázové kroky v Cloudflare

1. Cloudflare D1: vytvořit **samostatnou** databázi `isir-radar`.
   Nesmí to být stávající `isir-test` ani budoucí `isir-prod`.
2. Cloudflare Pages: projekt **isir-radar** vytváří automaticky GitHub
   Actions workflow `radar-pages.yml` přes Cloudflare Pages API. Používáme
   **Direct Upload z GitHub Actions**, nikoliv Cloudflare Git integration:
   push změn Radar na `main` automaticky publikuje `radar/public`.
   - V GitHub Secrets musí být `CLOUDFLARE_PAGES_API_TOKEN` s oprávněním
     `Account / Cloudflare Pages / Edit` jen pro potřebný Cloudflare účet.
   - Původní `CLOUDFLARE_API_TOKEN` zůstává pro D1 (nový token nemá být
     sdílený s crawlerem).
   - `functions/` se nahrává Wranglerem jako Pages Functions.
   - Nový projekt se vytváří jen tehdy, když `isir-radar` neexistuje.
   - U existujícího projektu propojeného s Git integration se tento
     mechanismus bez výslovného zásahu nepokouší měnit typ nasazení.
3. D1 databázový binding **DB** v Production a Preview nastavuje
   automaticky `radar/cloudflare_deploy_setup.py`. Skript odmítne jiné
   jméno databáze a ověří jurisdikci EU.
4. Cloudflare Zero Trust -> Access -> Applications: chránit celý projekt;
   přístup pouze pro svůj e-mail. **Nastavte Access i pro preview deploymenty**,
   nebo je pro běžné návštěvníky zakažte. Aplikace má navíc server-side
   ověřování JWT i identity.
5. Pages -> Settings -> Variables and Secrets (Production/Preview):
   - `ACCESS_TEAM_DOMAIN`: úplná URL `https://<team>.cloudflareaccess.com`
   - `ACCESS_AUD`: Audience Tag příslušné Access aplikace
   - `RADAR_ALLOWED_EMAIL`: jediný povolený e-mail (bez uvozovek)
6. Po nastavení bindingu a variables spustit nový deployment. Při chybě
   zabezpečení API ani stránky nebudou dostupné (fail closed).

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
- `functions/_middleware.js` – ověření Cloudflare Access (včetně statiky)
- `functions/api/properties.js` – filtrovaný katalog, ruční přidání
- `functions/api/properties/[id].js` – detail a úpravy vlastního hodnocení
- `radar/schema.sql` – normalizované tabulky
- `radar/import_legacy.py` – jednorázový import
- `test_radar.py` – lokální testy
