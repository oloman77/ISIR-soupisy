# ISIR: oprava fronty a ověření OCR, 9. 9. 2026

Pracovní návrh k doplnění pull requestu č. 1. Není nasazený.

## Nově opraveno
- Záznamy bez dokument_url se nepokoušíme opakovaně stahovat. Zůstávají přiznané mezi nedokončenými záznamy a mají vlastní počet missing_document_url. Je potřeba samostatně ověřit, zda je možné odkazy doplnit, nebo jde o události bez přílohy.
- Čtyři nové dokumenty se střídají s jedním dokumentem z historie nebo opakované kontroly. Starší fronta tak nezablokuje první zpracování nových dokumentů.
- Pevný limit zvýšen ze 150 na 500 dokumentů za běh. Časový rozpočet 15 minut zůstává. Toto samo o sobě není zárukou dostatečné kapacity.
- Web rozlišuje nedokončené záznamy a počet záznamů bez odkazu.
- Jedenáct regresních testů prošlo lokálně. Nové testy ověřují vynechání chybějících URL, střídání nové a historické fronty, pokračování po přerušení a restart při změně obsahu PDF.

## Naměřený přítok
Proud ISIR mezi 9. 9. 2026 10:58:57 a 11:22:08 Europe/Prague obsahoval v načteném vzorku 346 událostí, z toho 207 unikátních odkazů na dokument. Jde o krátký denní vzorek, nikoli 24hodinový průměr. Původní pevný limit 150 za 30 minut je pod tempem tohoto vzorku.
Zveřejněný přehled aktualizovaný v 09:14:40 UTC obsahoval 16 717 soupisových záznamů, 10 763 stavů no_url, 74 no_text a 4 534 dosud nekontrolovaných záznamů.

## Výsledek živého vzorku
Šest skutečných dokumentů: pět přečteno, jeden dlouhý sken byl po 40 OCR stranách označen partial:time_limit. Osmistránkový sken s majetkovými signály se přečetl za 28,75 s, třístránkový za 19,19 s. Tři textové dokumenty trvaly přibližně 9,5–9,7 s včetně sítě. Živý vzorek byl spuštěn před doplněním pokračování po přerušení.

## Rozsah
Zůstává OCR ces+eng pro stránky s méně než 100 znaky, opakování chyb s odstupem, čtení za stránkou 40 a sběr nových událostí s dokument_url. Historie mimo soupisy se zpětně nedoplňuje. Rozšířený sběr začne od uložené pozice při prvním nasazení.
Nálezy stále znamenají pouze signály možného nemovitého majetku, nikoli potvrzené vlastnictví dlužníka.

## Další ověření
- Vyhodnotit přiložené měření skutečných PDF (pilot-results.json). Síťové časy zdejšího prostředí nejsou měřením rychlosti GitHub Actions.
- Kapacitu prověřit v pilotu na GitHub Actions, ideálně přes celý den a mimo publikační workflow. Kontrolovat růst fronty.
- Nově se do rozpracovaného záznamu ukládá text a číslo dokončené stránky. Při příštím pokusu se pokračuje; změna SHA-256 obsahu PDF čtení restartuje. Po úspěchu se pomocná data odstraní. Pokračování je ověřeno regresním testem, nikoli druhým živým během dlouhého skenu. Rozpracované texty dočasně zvětší results.json. Přerušení celého procesu před uložením výsledků nadále může ztratit postup posledního běhu.
- Ranní briefing ani notifikace výpadků se těmito soubory nemění.

## Nahrání
Rozbalit ZIP. Do kořene větve isir-vylepseni přetáhnout crawler.py, test_crawler.py, CHANGES.md, pilot-results.json a celé složky docs a .github. Tím se aktualizuje stávající pull request a spustí regresní testy. Neuploadovat ZIP ani obalovou složku, neměnit data/state.json a docs/results.json. Před ostrým nasazením zbývá ověření provozní kapacity.
