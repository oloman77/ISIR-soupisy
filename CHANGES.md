# ISIR: návrh rozšíření sledování

Připraveno 9. 9. 2026. Nenasazeno. GitHub odmítl vytvoření větve chybou 403 Resource not accessible by integration.

## Obsah
- crawler.py: sběr všech nových událostí s odkazem na dokument, OCR stránek s méně než 100 znaky pomocí Poppler/Tesseract ces+eng, zrušení limitu 40 stran.
- Neúspěšné nebo částečné kontroly zůstávají nedokončené. Další pokus má odstup až 24 hodin. Staré výsledky se znovu přečtou novou verzí.
- Limit 120 sekund na dokument a rozpočet 15 minut pro část běhu včetně předchozího sběru chrání čas běhu; přerušení se nepovažuje za úspěch. Dlouhé dokumenty zatím mohou zůstávat k ručnímu dořešení, protože stránkový checkpoint není implementován.
- docs/index.html: upozornění na neaktuální data, nedokončené kontroly a rozsah historie.
- .github/workflows/isir.yml: instalace českého a anglického OCR.
- test_crawler.py a .github/workflows/tests.yml: sedm regresních testů.

## Ověření
Sedm lokálních testů prošlo: oprava starých chybných stavů, odstup opakování, viditelnost chyby OCR, smíšené PDF a stránka 41, odkaz s číslem spisu, sběr dokumentu mimo soupisy a správné počítání nedokončených kontrol.
PDF čtečka, síť a OCR jsou v těchto testech nahrazeny testovacími objekty. Kompilace Pythonu prošla. Skutečné české OCR ani úplný běh proti ISIR zatím nejsou ověřeny. Zdejší OCR nemá český jazykový balík; workflow jej instaluje.

## Bezpečný postup nasazení
1. Vytvořit pracovní větev ze současného main; porovnat případné změny od přípravy tohoto balíčku.
2. Nahradit pouze soubory v balíčku na odpovídajících cestách. Nemazat data/state.json ani docs/results.json. ZIP nenahrávat jako jeden soubor do repozitáře.
3. Otevřít pull request a spustit testy.
4. Před nasazením ověřit české OCR na skutečných dokumentech a změřit pilotní objem, dobu zpracování a růst fronty.
5. Po nasazení zkontrolovat první běh a web. Pokud fronta roste, navýšit kapacitu nebo převést frontu a výsledky do databáze mimo veřejný JSON.

## Omezení a další práce
- Rozšířené sledování začne od uloženého current_id při prvním běhu nové verze (all_documents_from_id). Starší dokumenty mimo soupisy NEJSOU zpětně doplněny.
- Pokrytí zahrnuje dokumenty dostupné přes dokument_url v proudu událostí; neověřuje úplnost všech příloh ve spise.
- OCR s hranicí 100 znaků nemusí zachytit obrázkovou část stránky s delší textovou vrstvou. Potřebuje další ověření na vzorku.
- Nálezy jsou pouze kandidáti podle klíčových slov. Vlastnictví dlužníka, negace, duplicity mezi řízeními a podrobnosti nemovitostí musí řešit další fáze.
- Nové dokumenty mají přednost před opakováním chyb. Při velkém přítoku může fronta růst. Úplnost není garantována.
- Ranní briefing, notifikace výpadků ani automatické odesílání tento balíček nezavádí a nemění.
- Dokončení produkčního hlídače vyžaduje pilot, sledování kapacity, doplnění historie a ověření doručování.
