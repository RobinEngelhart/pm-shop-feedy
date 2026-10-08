# P+M shop – převodník feedů dodavatelů pro Shoptet

Každé 3 hodiny stáhne feedy dodavatelů, převede je do formátu Shoptet XML
a vystaví je přes GitHub Pages:

    https://<uživatel>.github.io/pm-shop-feedy/<id-dodavatele>.xml

Přehled všech feedů a reporty (vyřazené a nezařazené položky) jsou na
`https://<uživatel>.github.io/pm-shop-feedy/`.

## Jak to funguje
- `suppliers.yml` – nastavení dodavatelů: mapování polí, opravy textů, pravidla kategorií, výpočet cen.
- `convert.py` – samotný převod.
- `.github/workflows/feedy.yml` – automatické spouštění (každé 3 h, při změně nastavení, nebo ručně).
- Adresy feedů dodavatelů jsou v secretu **FEED_URLS** (Settings → Secrets and variables → Actions),
  ve tvaru JSON: `{"vo-partner": "https://...", "dalsi": "https://..."}`. V repozitáři nejsou vidět.

## Přidání dalšího dodavatele
1. V `suppliers.yml` zkopírujte blok `sablona-heureka`, přejmenujte id, nastavte mapování polí a kategorie, `enabled: true`.
2. Do secretu FEED_URLS přidejte `"nove-id": "https://adresa-feedu"`.
3. V Shoptetu přidejte automatický import s adresou `https://<uživatel>.github.io/pm-shop-feedy/nove-id.xml`.

## Ochrany
- Když feed dodavatele přijde prázdný nebo rozbitý (méně než `min_items` produktů), starý výstup se nepřepíše.
- Chyba u jednoho dodavatele neovlivní ostatní.
- Nákupní ceny se do veřejného výstupu nedávají (`publish_purchase_price: false`).
- Výstup neobsahuje časové razítko, takže se mění jen při skutečné změně dat – Shoptet pak import zbytečně nespouští.

## Lokální test
    pip install pyyaml
    python convert.py --input vo-partner=tests/vo-partner-sample.xml
