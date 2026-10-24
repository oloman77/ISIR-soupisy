# ISIR — společná znalostní báze projektu

> **Stav zpracování:** 24. 10. 2026 – konsolidováno a technicky ověřeno proti repozitáři; historické chaty a jejich úplný obsah nejsou z GitHubu přímo dostupné, proto mohou obsahovat další dosud nezapsané souvislosti. Při novém zjištění dokument průběžně opravovat.  
> **Účel:** společný výchozí bod pro chaty „01 | Strategie & analýza“ a „02 | Vývoj & provoz“.  
> **Zdroj pravdy o kódu a provozu:** aktuální GitHub, workflow a ověřená data; tato stránka je rozcestník, nikoli náhrada technické dokumentace.
>
> **Značení:** **Ověřeno v repozitáři** = dohledáno v souboru/kódu; **historické měření** = naměřeno v minulém pilotu; **rozhodnutí** = schválený směr spolupráce; **hypotéza / neověřeno** = nutno teprve testovat. Existence souboru či úspěšná GitHub Action sama o sobě nedokazuje aktuální stav Cloudflare nebo veřejného ISIR.

## 1. Cíl a hranice

**Rozhodnutí:** co nejdříve odhalovat **konkrétní nemovitosti s potenciálem zpeněžení v insolvenčních řízeních**, sekundárně v exekucích. Nemovitost je důležitá svou **skutečnou polohou**, nikoli bydlištěm dlužníka. Primárně se zaměřujeme na **okresy Kutná Hora a Havlíčkův Brod**; seznam území má být konfigurovatelný (k. ú., obec, okres, kraj).

Požadované výstupy: katastrální území (ideálně kód), parcela/jednotka nebo jiná identifikace, okres a kraj, spisová značka, fáze řízení, datum první veřejné informace, **důkazní dokument s odkazem** a míra jistoty. Následně vyhodnotit, zda lze nemovitost skutečně nabýt; soupis ještě není potvrzený prodej.

**Klasifikace nálezu:**
1. **Zmínka/podezření**: v dokumentu se objevuje nemovitost, adresa, k. ú. či LV; vazba na majetkovou podstatu není doložena.
2. **Soupis doložen**: dokument věrohodně dokládá zahrnutí dané nemovitosti do majetkové podstaty (ne pouze sousední zmínku).
3. **Potenciál zpeněžení**: ocenění, pokyn, návrh či jiný konkrétní signál; nutno posoudit právní kontext.
4. **Potvrzená nabídka/prodej/dražba**: konkrétní veřejný zdroj, datum a podmínky; dostupnost průběžně ověřovat.
5. **Neznámé/nezpracované**: nečitelné PDF, nejednoznačná lokalita, chybějící příloha. **„Nenalezeno“ nesmí znamenat „dlužník nic nevlastní“.**

### Jak měřit úspěch

Vedle počtu záznamů měřit **precision** (podíl správných pozitivních nálezů), **recall/úplnost** (podíl zachycených relevantních případů z ručně ověřeného kontrolního vzorku), podíl doložených lokalit, cenu/čas na použitelný nález, zpoždění od zveřejnění události a reálnou obchodní využitelnost. Dosud **nemáme** validovanou celkovou přesnost ani úplnost; starší uváděná procenta jsou pouze hypotézy, ne výsledky.

### Princip 80/20: jednoduchost před složitostí (rozhodnutí 24. 10. 2026)

**Pracovní zásada pro oba chaty ISIR:** Nejdříve hledej nejmenší, nejlevnější a nejrychlejší způsob, jak ověřit obchodní hodnotu hypotézy. Paretovo pravidlo 80/20: soustřeďme se na malou část práce, která přináší většinu výsledku.

- **Nejdřív obchodní otázka, potom technologie:** jeden reálný případ a jednoduchý důkaz mají přednost před složitým crawlerem, infrastrukturu či velkým backfillem.
- **Malé, měřitelné testy:** stanov předem, co musí experiment potvrdit/vyvrátit, kolik práce stojí a kdy jej ukončíme.
- **Ochota změnit směr:** když důkazy chybí, postup se komplikuje nebo klesá přínos, zjednodušit, zastavit či změnit hypotézu; neobhajovat utopené náklady.
- **Kritické myšlení:** oddělovat fakta, domněnky a marketingová tvrzení. Aktivně hledat protiargumenty a levnější alternativy.
- **Nadšení až po důkazu:** teprve když najdeme správný, ověřený a obchodně životaschopný směr, dotáhneme technickou kvalitu, automatizaci a provoz naplno.
- **Ochrana hodnoty:** při změně směru nic zbytečně nemazat; zachovat funkční části, historická data a uživatelská hodnocení.

**Praktická otázka při každém dalším rozhodnutí:** „Jaký nejjednodušší test nám nyní dá nejvíc důkazů o reálné obchodní hodnotě — a co zatím vůbec nemusíme stavět?“

## 2. Organizace spolupráce

- **01 | Strategie & analýza**: právně a obchodně relevantní signály, zdroje, číselníky, metodika, rizika, piloty, měřítka kvality, rozhodnutí.
- **02 | Vývoj & provoz**: implementace, GitHub, testy, cloud, D1, bezpečné nasazování a opravy.
- **Historické chaty** (archivovat až po věcné kontrole tohoto dokumentu): „Fáze 2“, „Oprava selhání crawleru“, „Oprava denního přehledu“, „Navrhni hlídač insolvenčních řízení“. Jsou podklady pro dohledání souvislostí, ne samostatné aktuální pracovní proudy.
- Technické změny musí respektovat [společný provozní manuál KN Exploreru, větev preview](https://github.com/oloman77/KN-Explorer/blob/preview/docs/SHARED-INFRASTRUCTURE-PLAYBOOK.md). Před změnou číst i aktuální konfiguraci projektu. Repo **ISIR-soupisy** má podle kontroly k 24. 10. 2026 výchozí větev `main`; nelze automaticky přebírat rozdělení `preview/main` z jiných projektů. Experimenty připravovat v oddělené větvi a ověřovat před sloučením.
- **Neaktivovat původní masivní crawler** a nepřepisovat historická data nebo osobní hodnocení bez zvláštní analýzy a souhlasu.

## 3. Co máme — ověřeno v repozitáři

### 3.1 Starý ISIR crawler a archiv

- [`crawler.py`](../crawler.py): SOAP služba `https://isir.justice.cz:8443/isir_public_ws/IsirWsPublicService`, posun po ID událostí; ukládá datum, spisovou značku, `typ_udalosti`, `popis_udalosti`, poznámku a `dokument_url`. Součástí je OCR pro skeny, detekce slovních signálů nemovitostí a orientační geografické mapování.
- [`data/state.json`](../data/state.json) je **historický snímek**, jeho poslední zaznamenaný běh je **17. 9. 2026**. Z něj nelze usuzovat, že je systém dnes synchronizován s ISIR.
- [`docs/results.json`](results.json) je starší veliký datový archiv, při kontrole GitHubu přibližně **103 MB**. Nejde o vhodnou budoucí provozní databázi.
- **Původní automatizace byla k 24. 10. 2026 zakonzervována:** aktivní `.github/workflows/isir.yml` odstraněn a jeho původní obsah uložen v [`archive/legacy/isir.yml`](../archive/legacy/isir.yml). Původní definice spouštěla každý půlhodinový běh (`*/30 * * * *`), 90denní okno a až 500 PDF na běh. Změna ruší právě tento plánovaný/ručně spustitelný workflow; neodstraňuje kód, data ani piloty. Obnova vyžaduje nové schválení, nikoliv pouhý návrat starého YAML. Viz [konzervační postup](../archive/legacy/README.md).
- `crawler.py` používá u časti dokumentů slovní `SOUPIS_RX`; samotný oficiální číselník typů událostí dosud netvoří ověřený úplný prioritizační filtr. Čtení PDF v původní architektuře může být blokováno historickou frontou.

### 3.2 ISIR Radar

**Ověřeno v kódu / dokumentaci:** [`radar/README.md`](../radar/README.md), [`radar/schema.sql`](../radar/schema.sql), [`radar/public/index.html`](../radar/public/index.html), [`functions/`](../functions/) a [`.github/workflows/radar-pages.yml`](../.github/workflows/radar-pages.yml).

- Samostatný soukromý web na **Cloudflare Pages**; D1 databáze **`isir-radar`** je oddělená od starého crawleru i od KN Exploreru.
- Katalog, filtry podle okresu/stavu/priority/zdroje, detail, ruční přidání, vlastní názvy, poznámky, štítky, historie rozhodnutí a ruční úprava okresu.
- `property_decisions` a `decision_history` zachovávají **uživatelskou práci**; import ji nesmí resetovat.
- Historický import [`radar/import_legacy.py`](../radar/import_legacy.py) vytváří **provizorního kandidáta po dokumentu**, nikoliv automaticky ověřenou unikátní nemovitost. Označení okresu může být jen návrh.
- [`radar/import_public_offers.py`](../radar/import_public_offers.py) a [`radar/curated_offers.json`](../radar/curated_offers.json) obsahují **jednorázový ruční příklad** veřejného insolvenčního záměru (Vilémovice u Ledče nad Sázavou). Zveřejněná nabídka není zárukou, že je stále dostupná.
- Dokumentace popisuje zabezpečení přes HTTPS + Basic Auth a Cloudflare Secret `RADAR_LOGIN_PASSWORD`. Klíče a hesla nevkládat do GitHubu ani do chatu.
- Poslední nalezený úspěšný GitHub Actions běh nasazení Radaru při kontrole historie: [18. 10. 2026](https://github.com/oloman77/ISIR-soupisy/actions/runs/39114276118). **Nezaměňovat** to s aktuálním ověřením živé aplikace a stavu databáze.

### 3.3 KN Explorer — oddělený nástroj

Samostatný projekt [`oloman77/KN-Explorer`](https://github.com/oloman77/KN-Explorer) pro **cílené ověřování konkrétních nemovitostí v KN**. Neslučovat databáze ani API přístupy; nespouštět systematický průzkum všech parcel přes bezplatné REST API ČÚZK bez vyjasnění podmínek. ČÚZK/RÚIAN a oficiální číselníky jsou užitečné pro mapování **k. ú. → obec → okres → kraj**, ne automatický důkaz o vlastnictví nebo prodeji.

## 4. Co jsme zkusili a co jsme se naučili

| Předchozí práce / zdroj | Závěr a omezení |
| --- | --- |
| [`CHANGES.md`](../CHANGES.md), [`pilot-results.json`](../pilot-results.json) | **Historická měření (9/2026):** v krátkém vzorku 346 událostí / 207 unikátních URL na dokument; **nejde** o denní průměr ani počet soupisů. Čtení šesti PDF: pět dokončeno, jeden sken překročil 120 s (40 OCR stran); u dalších dokumentů desítky sekund nebo přibližně 10 s. Původní velký sběr má nepředvídatelnou kapacitu. |
| [`pilot/soupis_documents.py`](../pilot/soupis_documents.py), [`pilot/test_soupis_documents.py`](../pilot/test_soupis_documents.py) | Byl připraven omezený vzorek **20 kandidátů soupisu + 10 kontrolních dokumentů** s bezpečnostními limity a příznaky. Bez ručně verifikovaného výstupu nelze tvrdit, že těchto 30 dokumentů poskytlo úplný důkaz. |
| [`pilot/audit_six_plus_three.py`](../pilot/audit_six_plus_three.py) | Kontrola **6 geograficky zajímavých a 3 chybových PDF**; ochrana proti falešnému důkazu vlastnictví a oddělení OCR chyb. Výsledek čitelnosti není důkaz obchodní příležitosti. |
| [`pilot/case_trial.py`](../pilot/case_trial.py) | Opatrné spojování různých dokumentů stejného řízení: **neúplná spisová značka může spojit různé případy**. Při vazbě na řízení vyžadovat úplný jednoznačný identifikátor. |
| [`radar/audit_history.py`](../radar/audit_history.py), [`pilot/soupis_target_triage.py`](../pilot/soupis_target_triage.py) | Lokality v PDF jsou pouze **zmínky**; nelze z nich automaticky vyvozovat, že dotyčná parcela patří dlužníkovi nebo že bude prodána. Kraj nestačí pro potvrzení našeho okresu. |
| [`radar/probe_public_index.py`](../radar/probe_public_index.py) | Opatrné jednorázové zjišťování možností veřejného prodejního portálu, **nikoli potvrzené veřejné čtecí API** nebo povolení k hromadnému odběru. |

**Důležité historické rozhodnutí:** nepokračovat v plošném 90denním vytěžování PDF jen pro naději, že se někde objeví nemovitost. Přednost dostávají metadata nových událostí, cílené soupisy a dodatky; historický archiv **uchovat**, nikoli automaticky znovu procházet.

## 5. Zdroje a jejich skutečná role

1. **Oficiální ISIR webová služba** — hlavní zdroj **nových událostí**. Poskytuje metadata (ID, čas, typ, textový popis, spis, odkaz na dokument); **neposkytuje strukturovaný seznam parcel v majetkové podstatě**. Nutno zpracovat relevantní přílohu a sledovat nová podání i ve starých řízeních.
2. **Oficiální číselník událostí ISIR** — kandidát na levnou a přesnou předběžnou klasifikaci *události*, **ne** na spolehlivé určení obsahu PDF. Kompletní mapu kódů původních soupisů, doplnění, oprav a vedlejších příloh **ještě nemáme validovanou**.
3. **ČÚZK číselníky / RÚIAN** — normalizace názvů a kódů katastrálních území, obcí, okresů a krajů. Předběžné mapování je nutné spojit s důkazem, že právě daná nemovitost je součástí podstaty.
4. **Portál dražeb / insolvenční záměry, ASIS, Burza správců, weby správců, CEVD** — doplňkové **pozdější** indikátory skutečného zpeněžení; pokrytí je neúplné, přístup pro automatický odběr a licence nutno ověřit. Inzerát na webu správce může být jediný prodejní signál a nemusí obsahovat cenu ani prodejní kanál.
5. **Exekuční zdroje a KN** — další větev výzkumu, neplést se soupisy ISIR. Samotná plomba či obecná změna práv nemusí znamenat exekuci nebo budoucí prodej. Bezplatné REST API ČÚZK není povolená zkratka k plošnému vytěžování celé obce.
6. **Externí fulltextové indexy (např. Hlídač státu)** — **hypotéza pro cílené dohledání lokalit**, ne potvrzený úplný či licenčně dostupný API zdroj. Zkoumat až cíleným testem.

## 6. Nově schválený směr: sedmidenní pilot, ne nový masivní crawler

**Rozhodnutí:** nejdřív **samostatný read-only audit pouze metadat událostí zveřejněných za posledních 7 dní** (nikoli pouze řízení zahájených v tomto týdnu), bez stahování PDF, bez zásahu do Radaru/D1 a bez spouštění původního crawleru.

1. Získat aktuální číselník a ověřit skutečné vazby `typUdalosti` / `popisUdalosti`, varianty **původního soupisu, doplnění, změn, oprav**, vedlejších dokumentů, zpráv o stavu majetku a relevantních zpeněžovacích událostí.
2. Spočítat **skutečný počet** událostí a unikátních dokumentů za týden, podíly podle kódů, výskyt chybějících URL a objem P1/P2/P3. **Nemáme zatím podklad pro tvrzení „jen desítky soupisů denně“.**
3. Následně, až po vyhodnocení metadat, spustit malý kontrolovaný PDF pilot: orientačně **20 prioritních + 10 kontrolních PDF**, včetně obtížných/skenovaných případů a evidence technických selhání.
4. Měřit především *ztráty při filtraci*: kolik skutečných soupisů a doplnění se skrývá mimo vybrané kódy; dále doložení vztahu nemovitosti k podstatě, přiřazení lokalit a dobu od zveřejnění.
5. Na základě výsledků teprve schválit úzkou průběžnou pipeline. Nové dokumenty nesmějí čekat na historický OCR backlog; stará řízení je třeba **sledovat kvůli novým dokumentům**.

**Právní/obsahové nuance:** soupis majetkové podstaty se může během řízení doplňovat, opravovat i měnit; nemovitost může vzniknout jako nově nabytý majetek či být následně vyřazena. Jiný dokument může obsahovat soupis nebo relevantní majetkovou informaci i bez jednoznačného názvu. Existence nemovitosti v soupisu sama o sobě neprokazuje volnou obchodovatelnou nabídku, zvlášť u chráněného obydlí, spoluvlastnictví či sporného vlastnictví.

## 7. Otevřené otázky a rizika (dosud bez odpovědi)

- **Kódy ISIR:** existuje jedna nebo více jednoznačných kategorií soupisů? Jak se označuje doplnění, nahrazení, vedlejší příloha či soupis skrytý v obecně označené zprávě? Jaké jsou skutečné chyby klasifikace?
- **Úplnost:** kolik relevantních dokumentů námi vybraný filtr mine? Bez ručně ověřeného kontrolního vzorku to nelze vyčíslit.
- **Lokalita:** kde se lokalita skutečné majetkové položky liší od adresy dlužníka, soudu, správce nebo zajištění jiného vlastníka? Více parcel / krajů v jednom dokumentu nevyhodnocovat jedním nevysvětleným krajem.
- **Identita případu a nemovitosti:** stabilní párování úplné spisové značky, aktualizovaných dokumentů a jednotlivých parcel; zamezit vícenásobným provizorním „nemovitostem“ pro jeden majetek.
- **Aktuálnost:** vyřazení majetku, sporné položky, změna prodejního záměru, již uskutečněný prodej; určit režim pozdějšího sledování již nalezených řízení.
- **Provoz:** poslední dohledaný běh starého crawleru v GitHub Actions nastal **18. 9. 2026** (selhal); historický UI stav zapnuto/vypnuto nebyl přímo ověřen. Jeho workflow nyní archivujeme mimo aktivní `.github/workflows`. Dále je třeba při provozním auditu samostatně prověřit živý Radar a D1; nepovažovat úspěšnou starší GitHub Action za důkaz jejich aktuálního stavu.
- **Veřejná osobní data a licence:** minimalizovat ukládání osobních údajů, nepublikovat neveřejné poznámky, prověřovat právně přípustné zdroje a podmínky API.

## 8. Pravidla pro změny, aby se neopakovala minulost

- **Před každou technickou změnou:** přečíst společný [provozní manuál](https://github.com/oloman77/KN-Explorer/blob/preview/docs/SHARED-INFRASTRUCTURE-PLAYBOOK.md), tento soubor a projektovou dokumentaci; ověřit aktuální GitHub, větve, workflow, D1 a související testy.
- **Důsledně oddělovat:** návrh → malý read-only pilot → ruční verifikace → rozhodnutí → implementace → testy → ověřené nasazení.
- Do `main`, produkčních DB, automatizací ani secrets neměnit nic bez jasného schválení příslušného zásahu; informační/bezpečný pilot má být izolovaný.
- Existující tabulky `properties`, `property_sources`, `property_decisions`, `decision_history` a dosavadní data ponechat; změny verzovat, migrovat bezpečně, měřit vliv na ruční rozhodnutí.
- V pracovních zprávách a reportech vždy rozlišovat **potvrzený nález**, **podezření**, **neměřenou hypotézu**, **chybu čtení** a **neověřený provozní stav**.
- Zdrojový odkaz a datum zveřejnění ukládat odděleně od data našeho zjištění; nehlásit aktuálnost nabídky bez nové kontroly.

## 9. Kontrolní seznam před archivací historických chatů

V chatu „01 | Strategie & analýza“ věcně potvrdit:

- [ ] Sedí cíl: především **časně odhalit nemovitost v majetkové podstatě**, ne pouze již zveřejněnou dražbu.
- [ ] Platí výchozí území: **Kutná Hora + Havlíčkův Brod**, s možností volby dalších území.
- [ ] Jsou zachována rozhodnutí: **neobnovovat masivní crawler**, nevymazat historická data či soukromá hodnocení.
- [ ] Souhlasí hranice jistoty: **zmínka ≠ soupis ≠ zpeněžení ≠ potvrzený prodej**.
- [ ] Je správně zaznamenáno, co už Radar umí a co zatím **neumí**.
- [ ] Je jasný další krok: **sedmidenní metadata pilot bez PDF a bez DB změn**, potom malý ověřovací PDF vzorek.
- [ ] Nechybí klíčové poučení ze starších diskusí (geografie, velká fronta, OCR, weby správců, dražby, Cloudflare/D1).

**Archivaci chatů lze po této konsolidaci provést; nemažte je.** Dokument vznikl z dostupné historie a repozitáře, ne z kompletního exportu všech konverzací. Pokud se později objeví opomenutá skutečnost, doplnit ji bez nutnosti znovu aktivovat starý chat. Archivovaná konverzace zůstává použitelná pro dohledání původních souvislostí. Tento dokument postupně aktualizovat po **ověřených** rozhodnutích a experimentech, ne po každé dílčí debatě.

---

## Technické odkazy

- [Hlavní repozitář](https://github.com/oloman77/ISIR-soupisy)
- [Dokumentace ISIR Radar](../radar/README.md)
- [Historická měření a opravy](../CHANGES.md)
- [Historický šestidokumentový vzorek](../pilot-results.json)
- [Omezený pilot soupisů](../pilot/soupis_documents.py)
- [Audit devíti PDF](../pilot/audit_six_plus_three.py)
- [Analýza geografického přiřazení](../pilot/soupis_target_triage.py)
- [Sdílený provozní manuál](https://github.com/oloman77/KN-Explorer/blob/preview/docs/SHARED-INFRASTRUCTURE-PLAYBOOK.md)
