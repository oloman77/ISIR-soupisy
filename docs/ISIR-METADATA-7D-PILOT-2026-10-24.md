# ISIR – sedmidenní pilot metadat: technická zpráva pro 01 | Strategie & analýza

**Datum měření:** 24. 10. 2026 (Europe/Prague)  
**Stav:** živý omezený vzorek **naměřen**, úplné sedmidenní okno **NEPOKRYTO**.  
**Větev:** `pilot/7d-isir-event-metadata-20261024`, PR #21 (ponecháno bez sloučení do `main`).  
**Živý běh:** https://github.com/oloman77/ISIR-soupisy/actions/runs/40124703735  
**Artefakt:** https://github.com/oloman77/ISIR-soupisy/actions/runs/40124703735/artifacts/12573755158  
**Ověření oficiálního číselníku:** https://github.com/oloman77/ISIR-soupisy/actions/runs/40125761126

## 1. Zadání a zdroje

Účel: změřit relevanci oficiálních kódů `typUdalosti` / `popisUdalosti` pro vyhledání soupisů majetkové podstaty, doplnění, oprav a dalších majetkových akcí v posledních sedmi dnech, nezávisle na roce zahájení insolvenčního řízení.

- Oficiální dokumentace MSp: https://isir.justice.cz/isir/help/Popis_WS_1_v2_10.pdf (WS_1, verze 2.10).
- Oficiální číselník MSp: https://isir.justice.cz/isir/help/Cis_udalosti.xls.
- Provozní manuál: `oloman77/KN-Explorer`, větev `preview`, `docs/SHARED-INFRASTRUCTURE-PLAYBOOK.md`.
- Znalostní báze: `docs/PROJECT-KNOWLEDGE-BASE.md`.

Služba WS_1 vrací publikované akce sekvenčně podle ID (až cca 1000 na dávku), **bez filtru kalendářního data**; doporučený interval volání je minimálně 10 minut. Akce představují nové i starší řízení. Dokumenty jsou pouze odkazované, nikoli součástí SOAP odpovědi.

## 2. Skutečné měření živé služby (nikoli archiv)

Časové okno požadované pro úplný týden:
`2026-10-17T19:18:58Z` až `2026-10-24T19:18:58Z`.
V ČR jde přibližně o 17. 10. 21:18 až 24. 10. 21:18 SELČ.

Úmyslně omezený přístup: **2 SOAP požadavky** (získání posledního ID a jedna dávka), rozestup minimálně 600 sekund, žádná PDF. Poslední ID při první kontrole: **81098464**; požadována dávka akcí s ID větším než **81097664**.

| Metrika | Naměřeno | Způsob interpretace |
|---|---:|---|
| Načtených akcí | **22** | Pouze omezená čerstvá dávka |
| Unikátních neprázdných URL dokumentů | **22** | URL ≠ ručně ověřené unikátní PDF |
| Akce bez URL dokumentu | **0** | Jen v této dávce |
| Různých kódů `typUdalosti` | **6** | Reálné kódy v omezeném vzorku |
| Dvojic `typUdalosti` + `popisUdalosti` | **6** | Po jedné popisné variantě |
| Událostí ze starších ročníků řízení | **13** | Názorný důkaz potřeby sledovat starší řízení |
| Pozitivních soupisových kandidátů P1 v dávce | **0** | **NENÍ sedmidenní počet** |
| Nejednoznačně klasifikovaných popisů | **0** | Pouze v této dávce |
| Chybných dat zveřejnění | **0** | Pouze v této dávce |
| Duplicitních ID akcí | **0** | Pouze v této dávce |

Časy zveřejnění ve vzorku: **24. 10. 2026 18:22:04–20:41:34 SELČ**. Nezačínají u požadované hranice 17. 10. a ani nepokrývají úplně závěr okna. Kontrola hlásí `PARTIAL_NOT_SEVEN_DAY_TOTAL` s `covers_start=false`, `covers_end_with_20min_grace=false`, `seven_day_coverage_verified=false`. Byly zaznamenány 3 skoky v ID (nejde automaticky o prokazatelně chybějící události). Neproběhlo dost dotazů na ověření pokrytí celé časové posloupnosti.

**Úplný počet událostí/dokumentů za 7 dní ani počet PDF denně zatím NELZE VYČÍSLIT.** Číslo 22 se nesmí extrapolovat na týden.

### Přesná skladba 22 živých akcí

| Typ | Popis | Akcí | Katalog |
|---|---|---:|---|
| 636 | Znepřístupnění údajů o dlužníkovi dle § 425 IZ | 10 | shoda s číselníkem |
| 63 | Přihláška pohledávky | 7 | shoda |
| 124 | Usnesení o odmítnutí přihlášky | 2 | shoda |
| 195 | Výzva na správce | 1 | shoda |
| 563 | Doplnění/oprava/změna přihlášené pohledávky | 1 | shoda |
| 593 | Usnesení o část. odmítnutí přihlášky | 1 | shoda |

Výše uvedených šest kódů a textů je skutečně přítomno v živé dávce a bylo porovnáno se staženým oficiálním číselníkem v samostatném katalogovém běhu.

## 3. Oficiální číselník – ověřené klasifikační kódy

Úspěšně načten celý hlavní list `Cis_udalosti.xls`: 1078 unikátních kódů, z nichž 211 má v číselníku poznámku „již se nepoužívá“. Formát kódů v Excelu je **`I_334`**, zatímco v SOAP `typUdalosti` je číslo **`334`**; nutná normalizace prefixu `I_`.

| SOAP kód | Přesný název podle číselníku | Aktuálnost | Návrh priority |
|---|---|---|---|
| **334** | Soupis majetkové podstaty | Není označeno jako zastaralé | P1 |
| **454** | Soupis majetkové podstaty - doplnění | Není označeno jako zastaralé | P1 |
| **538** | Soupis majetkové podstaty - změna | Není označeno jako zastaralé | P1 |
| **361** | Soupis majetkové podstaty | Označeno již se nepoužívá | Historický / kontrolní |
| **453** | Soupis majetkové podstaty | Označeno již se nepoužívá | Historický / kontrolní |
| 486 | Vyrozumění o soupisu majetkové podstaty | Není označeno jako zastaralé | P2, obsah nejistý |
| 50 | Zpráva o průběhu zpeněžení | Není označeno jako zastaralé | P2 |
| 347 | Návrh na vydání souhlasu se zpeněžením MP mimo dražbu | Není označeno jako zastaralé | P2 |
| 1081 | Vyhláška o zpeněžení majetku | Není označeno jako zastaralé | P2 |
| 1087 | Zpráva IS o zpeněžení majetku | Není označeno jako zastaralé | P2 |
| 131 | Usnesení o upuštění od provedení soupisu majetku | Není označeno jako zastaralé | Spíše negativní signál, **ne soupis** |

**Kód samotný nevypovídá o skutečné nemovitosti ani o příležitosti k nákupu.** Ověřena je existence kódu a jeho popisu v číselníku, nikoli citlivost a úplnost filtru vůči reálným PDF.

## 4. Zjištěná omezení a rizika

1. WS_1 **nemá parametr datum od/do**. Pro úplný týden musí odběratel projít souvisle potřebné dávky ID až za spodní časovou hranici. Dvoupožadavkový test proto není sedmidenním soupisem událostí.
2. Oficiální doporučení minimálně 10 minut mezi dotazy jednomu subjektu znesnadňuje rychlý počáteční backfill, nikoliv nutně průběžné sledování.
3. Dokument může být připojen k události **později** opakovanou akcí stejného typu. Je třeba deduplikovat akce vůči skutečným dokumentovým URI a sledovat pozdní přílohy.
4. Reálná dávka může obsahovat starší insolvenční řízení. **Nefiltrovat podle data zahájení řízení.**
5. Volné popisy dokumentů a vedlejší dokumenty mohou schovávat relevantní majetkový obsah mimo hlavní P1 typy; **recall zatím nezměřen**.
6. Metrika 22 unikátních URL nezaručuje 22 různých majetkových PDF ani aktuální počet relevantních soupisů.

## 5. Závěr a doporučení pro 01 | Strategie & analýza

**Technická hypotéza podpořená číselníkem:** selektivní prioritizace podle **334 / 454 / 538** je realistický výchozí bod. **Neověřeno:** reálné sedmidenní objemy, přesnost/úplnost, potřebná denní OCR/PDF kapacita, podíl soupisů skrytých pod jinými kódy.

Nejbližší koncepční rozhodnutí: schválit způsob **souvislého sedmidenního dokončovacího sběru při respektování limitů WS_1**, např. řízený, kontrolovatelný backfill přes více etap (bez PDF a DB změn), s checkpointem, úplností časového okna a sledováním změn URL a servisních akcí. **Bez tohoto měření nepřecházet k průběžnému stahování PDF.**

## 6. Bezpečnost / změny

- Žádné stažené PDF.
- Žádné změny D1, Radaru, uživatelských hodnocení či historického archivu.
- Původní crawler a jeho archivované workflow nezměněny.
- Nové testy/skripty jsou pouze v samostatné větvi; do `main` se neslučují bez vyhodnocení.
- Živá WS_1 použita pouze dvakrát s odstupem nejméně 10 minut; následné ověření Excelu pouze GET katalogu.
