# ISIR Radar — rané dokumenty ISIR a WSDP 3.1: kontrolní technická zpráva

**24. října 2026 — výzkumná fáze / READ-ONLY**  
**PR:** https://github.com/oloman77/ISIR-soupisy/pull/22  
**Živé experimenty:** https://github.com/oloman77/ISIR-soupisy/actions/runs/40130392552 a https://github.com/oloman77/ISIR-soupisy/actions/runs/40130671446  
**Zdroj dat:** historický snapshot 17. 9. 2026, `docs/results.json`. Nové soupisy ani nové vlastníky jsme neprohlašovali za ověřené.

## 1. Metadatový sedmidenní pilot — NEDOKONČENÉ POKRYTÍ

Předchozí schválený live metadata pilot (PR #21, https://github.com/oloman77/ISIR-soupisy/actions/runs/40124703735) ověřil **22 akcí, 22 unikátních dokumentových URL a 6 typů událostí**, avšak pouze v krátkém časovém úseku **24. 10. 2026 18:22–20:41 SELČ**. Z toho 13 akcí náleželo ke starším ročníkům insolvenčních řízení. **Není to měření sedmidenního přítoku a nelze z něj odvozovat denní počty PDF.**

ISIR WS_1 má sekvenční přístup přes ID, nepodporuje přímý interval publikace a oficiální dokumentace doporučuje alespoň deset minut mezi žádostmi stejného odběratele. Dokončení celého týdne vyžaduje další plánované a kontrolované etapy až do překročení počáteční hranice, deduplikaci a kontrolu servisních událostí. Nyní k tomu nebyl povolen další dlouhý provozní workflow; **stav 7denního dokončení zůstává nezměněn**.

Kódy soupisů potvrzené z oficiálního XLS katalogu (ne však citlivost vůči obsahu PDF): `334` soupis, `454` doplnění, `538` změna. Historické `361` a `453` číselník označuje jako již nepoužívané. Třídění raných podání vyžaduje samostatné ověření konkrétních `typUdalosti`.

## 2. Rané dokumenty: právní předpoklad a reálný experiment

**Právní/obsahový předpoklad:** § 104 insolvenčního zákona požaduje u insolvenčního návrhu **podávaného dlužníkem** seznam jeho majetku. Návrh věřitele se touto povinností dlužníka automaticky neřídí. Rané podání může mít oddělené přílohy, ne vždy strojově čitelný seznam.

**Kandidátní názvy typů ze skutečného archivu (bez ověřených číselných kódů):**
- `Insolvenční návrh spojený s návrhem na povolení oddlužení`;
- `Návrh – přílohy`;
- `Insolvenční návrh spojený s návrhem na prohlášení konkursu`;
- samostatné nebo doplněné `Seznam majetku`, bude-li prokazatelně publikován.

**Nový malý historický test:** read-only skript `pilot/early_asset_case_study_20261024.py` deterministicky zvolil 9 odlišných raných PDF z archivu. Výsledek:

| Ukazatel | Naměřeno |
|---|---:|
| Unikátních historických PDF | 9 |
| Z nich stažitelných a čitelných parserem | 9 |
| PDF s použitelnou textovou vrstvou na některých kontrolovaných stranách | 8 |
| PDF bez této textové vrstvy na kontrolovaných stranách | 1 |
| PDF s obecnou majetkovou textovou zmínkou | 1 |
| PDF s jednoznačně identifikovanou kombinací k. ú./parcela/LV | 0 |
| PDF s potvrzenou nemovitostí v majetkové podstatě | 0 |
| Spolehlivě ověřených raný dokument → pozdější soupis | 0 |
| Změřený časový předstih | **Není měřitelný** |

Devět PDF představovalo dohromady přibližně 103 stran, ale u jednoho 38stránkového dokumentu jsme kontrolovali pouze prvních 25 stran; **bez OCR**. Proto uvedené nuly neznamenají, že dané dokumenty neobsahují majetek.

Historický archiv má **25 114 skupin pod zkrácenou spisovou značkou**; v průzkumu bylo **633 skupin s ranou událostí a bez nalezeného soupisu v archivních záznamech**. Nalezeno **0 možných párů raný dokument → pozdější soupis** na stejný archivní klíč. To neprokazuje absenci pozdějšího soupisu v ISIR, protože archiv je časově neúplný a spisové značky mohou postrádat označení soudu. Ani případný pár by bez plné identity řízení nebyl bezpečný důkaz.

**Úspěšnost za oba cílové okresy:** v tomto experimentu 0 potvrzených lokalizací z 9 PDF, což **není odhad obecné precision/recall**, protože výběr byl celorepublikový a žádná položka neměla potvrzenou nemovitost.

**Technický závěr:** dostupnost raných dokumentů byla v malém pilotu 9/9; získání parcel z textu potvrzeno nebylo. Výhoda časového předstihu zůstává hypotézou.

## 3. WSDP 3.1 — skutečně ověřené smluvní a technické vlastnosti

Primární zdroj aktuální dokumentace:
https://www.cuzk.gov.cz/Aplikace-DP-do-KN/Aplikace-DP-do-KN/Webove-sluzby-dalkoveho-pristupu.aspx
Technické ZIP (platnost od května 2026) `WSDP_10_4_2026.aspx`. Oficiální ZIP byl úspěšně stažen pro **offline inspekci WSDL/XSD**; bez jediného volání skutečné produkční nebo testovací WSDP služby.

Dokumentační soubory `ISKN/ws3_1/wsdp/*.wsdl` a `*.xsd` potvrzují tyto metody a požadavky:

| Funkce | Operace | Ověřené vstupy v XSD |
|---|---|---|
| Vyhledání oprávněného subjektu | `najdiOS` | Právnická osoba: `ico`, `nazev` (dle větve XSD). Fyzická osoba: `jmeno`, `prijmeni`, volitelně `rc` nebo `datumNarozeni`, volitelně `adresniUdaje`, `datumK`. Přesné validační závislosti jednotlivých podmínek by vyžadovaly validní testovací requesty. |
| Přehled vlastnictví | `generujPrehledVlastnictvi` | Povinné `osId`; volitelná volba `krajKod` **nebo** `obecKod`; volitelně `typPravnihoVztahuKod`, `datumK` a společné parametry sestavy. |
| Přehled vlastnictví s nemovitostmi | `generujPrehledVlastnictviSNemovitostmi` | Stejné: `osId`, volitelně `krajKod` nebo `obecKod`, `typPravnihoVztahuKod`, `datumK`, parametry sestavy. |
| Evidence práv pro osobu | `generujEvidenciPravProOsobu` | Povinné `typ`, `nazev`, `rcIco`, parametry sestavy. Pouhé jméno osoby není obecně dostatečný vstup. |
| Běžné parametry sestavy | `SestavyBaseType` | `format`, volitelně `verze`, `pripojitXML`, případně údaje k osvědčení výstupu. |

**Územní filtr:** V obou žádostech o přehled vlastnictví XSD neposkytuje přímo `okresKod`. Umožňuje **kraj** či **obec**. Pro okresy Kutná Hora a Havlíčkův Brod by bylo nutné rozvrhnout zjišťování s ohledem na územní rozsah, případně filtrovat celkový výsledek lokálně. Předpoklad, že jeden požadavek omezený pouze na okres je v tomto rozhraní zdarma, nemá oporu ve schématu/ceníku.

**Negativní výsledek:** Oficiální popis služby `Evidence práv pro osobu` explicitně uvádí, že sestava vzniká i tehdy, pokud subjekt nemá zapsaná žádná práva. Nulový výsledek proto **nepovažovat za bezplatný**. Ceník nemá uvedenou obecnou výjimku pro negativní výstup; skutečný okamžik účtování je třeba respektovat podle smluvního režimu WSDP.

**Testovací prostředí:** testovací 3.1 je **bezplatné, obsahuje fiktivní/anonymizovaná data vzorku z katastrálního pracoviště Prachatice**. Neověřuje reálné vlastnictví fyzických osob v našich okresech. Dle aktuálních aktualit ČÚZK byla testovací 2.9 v září 2026 zrušena, takže používat 3.1.

**Oficiální sazby:**
- 150 Kč / výstup `Evidence práv pro osobu` nebo `Přehled vlastnictví` (položky 5007, 5008 pro XML);
- 200 Kč / výstup `Přehled vlastnictví s nemovitostmi` (5013 pro XML);
- 100 Kč za výpis z LV (5001 pro XML), 10 Kč za informaci o parcele (5002 pro XML).
Zdroj: https://www.cuzk.gov.cz/Aplikace-DP-do-KN/Aplikace-DP-do-KN/Uctovani-vystupu-z-KN-poskytovanych-DP-A-WSDP.aspx.

**Důležité:** Sazby za výstup nejsou důkazem ceny za pouhý technický vyhledávací dotaz `najdiOS`. Není ověřeno, jak se u konkrétní WSDP smlouvy účtují negativní technické vyhledávací operace; ani bezplatnost, ani paušální zpoplatnění nelze bez podmínek automaticky přisuzovat.

## 4. Objem a náklad na použitelný nález

**Skutečné aktuální denní počty:** nelze odvodit ze 22akcového vzorku živých metadat ani ze 9 PDF. Neexistuje validované rozdělení počtu raných seznamů, kolik z nich identifikuje nemovitost a kolik je relevantních pro dva cílové okresy.

Vlastní matematický scénář, **nikoli výsledek pilotu**: 100 produkčních výstupů `Přehled vlastnictví s nemovitostmi` za 200 Kč = **20 000 Kč** pouze v poplatcích ČÚZK. Při 5 použitelných nálezech z těchto 100 jde o **4 000 Kč/nález**; při 20 nálezech o **1 000 Kč/nález**. U sestavy za 150 Kč: 100 × 150 = 15 000 Kč; při 5/20 nálezech **3 000 / 750 Kč na nález**. Náklady práce, OCR a infrastruktury jsou navíc a **nebyly změřeny**.

Vzorec: `náklad_na_nález = (150 × počet_150Kč_výstupů + 200 × počet_200Kč_výstupů + práce + OCR + infrastruktura) / počet_ověřených_použitelných_nálezů`. Pro 0 potvrzených nálezů je tato cena zatím nedefinovaná, nikoliv 0 Kč.

## 5. Rizika ztráty relevantních případů

1. Raný seznam majetku není přiložen pod jednoznačnou událostí, je skryt v jiném podání nebo je naskenovaný bez textové vrstvy.
2. Seznam dlužníka může obsahovat nepřesné, sporné nebo neaktuální údaje; není automaticky soupisem majetkové podstaty.
3. Sledování pouze několika `typUdalosti` může přehlédnout přílohy, opravy a pozdější doplnění.
4. Datový archiv neobsahuje souvislou historii řízení, takže bez dohledání originální úplné spisové značky mohou vznikat chybná párování.
5. Region nemovitosti nelze bezpečně odvodit z bydliště/sídla dlužníka ani ze soudní příslušnosti.
6. WSDP dostupnost a plnění povinných identifikátorů vlastníka mohou vytvářet selekční zkreslení; územní volba kraj/obec není přímý filtr dvou okresů.
7. Náklady na produkční WSDP při plošném vyhledávání mohou převýšit obchodní hodnotu nalezených případů.

## 6. Doporučený nejmenší další experiment — návrh k rozhodnutí v 01

**Vybrat 6 skutečných, časově dohledatelných insolvenčních řízení s úplnou spisovou značkou a doloženým pozdějším soupisem.** Záměrně kombinovat nejméně 3 s nemovitostí doloženou v soupisu a 3 kontrolní bez takové nemovitosti.

U každého ručně dohledat prvotní dlužnický návrh a jeho seznam majetku, jakož i pozdější soupis. Dle potřeby zpracovat cíleným OCR pouze několik stran, nikoliv celé PDF fronty. Uložit jen úroveň důkazu, datum zveřejnění, existenci parcely/LV/k. ú., potvrzený okres a změřený předstih prvního jednoznačného identifikátoru vůči pozdějšímu soupisu.

**Kritérium rozhodnutí:** mezi skutečně existujícími nemovitostmi zjistit, v kolika případech raný dokument poskytne identifikátor nemovitosti a kolik dnů reálného předstihu přinese bez zásadní ztráty přesnosti. Vše ostatní je hypotéza.

WSDP samostatně ověřit maximálně několika testovacími požadavky v bezplatném prostředí 3.1 na **fiktivních datech**, validovat přesný vstup/output, negativní případ, podporu `krajKod`/`obecKod` a simulované vyčíslení poplatků. **Žádné produkční dotazy bez rozpočtu a schválení.**

## 7. Stav a bezpečnost

- Původní masivní crawler, produkční Cloudflare Pages, D1, historie, uživatelská hodnocení **nezměněny**.
- Jednorázový dočasný workflow `.github/workflows/_TEMP-early-asset-wsdp-review.yml` byl po úspěšné inspekci **smazán z pracovní větve**.
- Není žádná nová trvalá automatizace ani produkční nasazení.
- PR #22 je pracovní výzkumná větev určená ke čtení a archivaci výsledků, nikoliv ke sloučení bez rozhodnutí.
