#!/usr/bin/env python3
"""
P+M shop – převodník feedů dodavatelů do formátu Shoptet XML.

Pro každého dodavatele v suppliers.yml:
  1. stáhne jeho XML feed (URL se bere z proměnné prostředí FEED_URLS – JSON {id: url}),
  2. přečte položky podle mapování polí,
  3. vyčistí data, zařadí do kategorií e-shopu a spočítá prodejní cenu,
  4. zapíše docs/<id>.xml ve formátu Shoptet (schéma products-supplier-v10)
     a docs/<id>-report.txt s přehledem (počty, vyřazené a nezařazené položky).

Spuštění lokálně:  FEED_URLS='{"vo-partner":"https://..."}' python convert.py
Test ze souboru:   python convert.py --input vo-partner=tests/vo-partner-sample.xml
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.request
from copy import deepcopy
from datetime import date
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "docs"
STATE_DIR = ROOT / "state"


# ---------------------------------------------------------------- pomocné funkce

def to_number(value):
    """'30,5' / '30.50' / ' 79 ' -> float, jinak None."""
    if value is None:
        return None
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return None
    return float(text)


def to_price(value):
    """Cena může mít za číslem měnu: '299.00 CZK', '1 299,00 Kč'."""
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)(CZK|Kč|,-)?", text, re.IGNORECASE)
    return float(m.group(1).replace(",", ".")) if m else None


def fmt_price(value: float) -> str:
    return f"{value:.2f}"


def round_price(value: float, rule: str) -> float:
    """Zaokrouhlení prodejní ceny.
    nines  – od 50 Kč nahoru na ...9 (79, 189, 609), pod 50 Kč na celé koruny nahoru
    whole  – na celé koruny nahoru
    none   – bez zaokrouhlení (2 desetinná místa)
    """
    if rule == "none":
        return round(value, 2)
    if rule == "whole":
        return float(math.ceil(value))
    if value >= 50:
        return float(math.ceil(value / 10) * 10 - 1)
    return float(math.ceil(value))


NS: dict = {}   # jmenné prostory aktuálního dodavatele, např. {"g": "http://base.google.com/ns/1.0"}


def get_field(item: ET.Element, path: str | None) -> str:
    """Hodnota pole položky. Cesta může být vnořená ('PARAM/VAL') nebo s prefixem ('g:price').
    Vrací prázdný řetězec, když pole chybí."""
    if not path:
        return ""
    node = item.find(path, NS)
    if node is None:
        # zkusit bez ohledu na velikost písmen
        low = path.lower()
        for child in item:
            if child.tag.lower() == low:
                node = child
                break
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def get_all(item: ET.Element, paths) -> list[str]:
    """Všechny hodnoty pole; paths může být jedna cesta nebo seznam cest."""
    if not paths:
        return []
    if isinstance(paths, str):
        paths = [paths]
    out = []
    for path in paths:
        out += [n.text.strip() for n in item.findall(path, NS) if n.text and n.text.strip()]
    return out


def match_rule(rule: dict, data: dict) -> bool:
    """Pravidlo pasuje, když pasují všechny uvedené podmínky (regex, bez ohledu na velikost písmen)."""
    checks = {
        "code": data["code"],
        "name": data["name"],
        "category": data["supplier_category"],
        "manufacturer": data["manufacturer"],
        "text": f"{data['name']} {data['description'][:500]}",
    }
    used = False
    for key, value in checks.items():
        pattern = rule.get(key)
        if pattern is None:
            continue
        used = True
        if not re.search(pattern, value or "", re.IGNORECASE):
            return False
    return used


def html_paragraphs(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if re.search(r"<(p|br|ul|li|h\d|strong|b)\b", text, re.IGNORECASE):
        return text  # dodavatel už posílá HTML
    esc = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return "<p>" + esc + "</p>"


def short_text(text: str, limit: int = 220) -> str:
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) <= limit:
        return plain
    cut = plain.rfind(" ", 0, limit - 20)
    return plain[: cut if cut > 0 else limit] + "…"


# ---------------------------------------------------------------- převod jedné položky

def convert_item(item: ET.Element, cfg: dict, defaults: dict, report: dict):
    f = cfg["fields"]
    data = {
        "code": get_field(item, f.get("code")) or get_field(item, f.get("code_fallback")),
        "ean": get_field(item, f.get("ean")),
        "name": get_field(item, f.get("name")),
        "description": get_field(item, f.get("description")),
        "manufacturer": get_field(item, f.get("manufacturer")),
        "images": get_all(item, f.get("image")),
        "stock": get_field(item, f.get("stock")),
        "purchase_price": get_field(item, f.get("purchase_price")),
        "price_vat": get_field(item, f.get("price_vat")),
        "sale_price_vat": get_field(item, f.get("sale_price_vat")),
        "rrp": get_field(item, f.get("rrp")),
        "vat": get_field(item, f.get("vat")),
        "weight_g": get_field(item, f.get("weight_g")),
        "supplier_category": get_field(item, f.get("category")),
        "gpsr": get_field(item, f.get("gpsr")),
    }

    # --- vyřazení nekompletních / chybných položek
    skip = cfg.get("skip", {})
    if not data["code"]:
        report["skipped"].append(f"(bez kódu) {data['name']}")
        return None
    if data["code"] in skip.get("codes", []):
        report["skipped"].append(f"{data['code']} – vyřazeno v konfiguraci")
        return None
    if not data["name"] or data["name"] in skip.get("names", []):
        report["skipped"].append(f"{data['code']} – chybí název")
        return None
    for rule in cfg.get("exclude", []):
        if match_rule(rule, data):
            report["skipped"].append(f"{data['code']} {data['name']} – {rule.get('reason', 'vyřazeno pravidlem')}")
            return None
    pricing = {**defaults.get("pricing", {}), **cfg.get("pricing", {})}
    retail_mode = pricing.get("mode") == "retail"
    buy = to_price(data["purchase_price"])
    if retail_mode:
        retail = to_price(data["price_vat"])
        sale = to_price(data["sale_price_vat"])
        if pricing.get("use_sale_price", True) and sale and retail and 0 < sale < retail:
            retail = sale
        if not retail or retail <= 0:
            report["skipped"].append(f"{data['code']} – chybí prodejní cena")
            return None
    elif buy is None or buy <= 0:
        report["skipped"].append(f"{data['code']} – chybí nákupní cena")
        return None

    # --- oprava textů
    name = data["name"]
    for wrong, right in cfg.get("name_fixes", {}).items():
        name = name.replace(wrong, right)
    name = re.sub(r"\s+", " ", name).strip().rstrip("<").strip()

    manufacturer = cfg.get("manufacturer_map", {}).get(data["manufacturer"], data["manufacturer"])

    description = data["description"]
    rrp_num = to_number(data["rrp"])
    # u některých položek dodavatel vloží popis omylem do pole doporučené ceny
    if rrp_num is None and len(data["rrp"]) > 50 and len(description) < 20:
        description = data["rrp"]
    desc_html = html_paragraphs(description)
    if data["gpsr"] and cfg.get("append_gpsr", True):
        gpsr = data["gpsr"]
        for wrong, right in cfg.get("text_fixes", {}).items():
            gpsr = gpsr.replace(wrong, right)
        desc_html += "<h3>Informace o výrobci</h3>" + html_paragraphs(gpsr)

    # --- kategorie
    category = None
    rule_vat = None
    for rule in cfg.get("categories", []):
        if match_rule(rule, {**data, "name": name}):
            category = rule["path"]
            rule_vat = rule.get("vat")
            break
    if category is None:
        category = cfg.get("fallback_category", defaults.get("fallback_category", "Ke kontrole"))
        report["unmatched"].append(f"{data['code']} {name} (kategorie dodavatele: {data['supplier_category'] or '-'})")

    # --- DPH a ceny
    vat = to_number(data["vat"])
    vat_map = {str(k): v for k, v in cfg.get("vat_map", {}).items()}
    if data["vat"] in vat_map:
        vat = float(vat_map[data["vat"]])
    if vat is None and rule_vat is not None:
        vat = float(rule_vat)
    if vat is None or vat not in (0.0, 12.0, 21.0):
        vat = float(pricing.get("vat_default", 21))
    coef = float(pricing.get("coef", 1.78))
    min_ratio = float(pricing.get("rrp_min_ratio", 1.3))
    # doporučenou cenu dodavatele (s DPH) bereme, jen když dává rozumnou marži
    if retail_mode:
        rc = float(pricing.get("retail_coef", 1.0))
        price_vat = retail if rc == 1.0 else round_price(retail * rc, pricing.get("rounding", "nines"))
        report["priced_rrp"] += 1
    elif pricing.get("use_rrp", True) and rrp_num and rrp_num > buy * min_ratio:
        price_vat = rrp_num
        report["priced_rrp"] += 1
    else:
        price_vat = round_price(buy * (1 + vat / 100) * coef, pricing.get("rounding", "nines"))
        report["priced_coef"] += 1

    stock_map = {str(k).lower(): v for k, v in cfg.get("stock_map", {}).items()}
    if data["stock"].lower() in stock_map:
        stock = int(stock_map[data["stock"].lower()])
    else:
        stock = to_number(data["stock"])
        stock = max(0, int(stock)) if stock is not None else 0
    raw_code = re.sub(r"\s*-\s*", "-", data["code"]).replace(" ", "")   # 'UB3 - A5' -> 'UB3-A5'
    code = cfg.get("code_prefix", "") + raw_code

    # --- sestavení SHOPITEM (pořadí prvků schéma nevyžaduje)
    si = ET.Element("SHOPITEM")
    ET.SubElement(si, "NAME").text = name
    if description.strip():
        ET.SubElement(si, "SHORT_DESCRIPTION").text = html_paragraphs(short_text(description))
    if desc_html:
        ET.SubElement(si, "DESCRIPTION").text = desc_html
    if manufacturer:
        ET.SubElement(si, "MANUFACTURER").text = manufacturer
    if cfg.get("supplier_name"):
        ET.SubElement(si, "SUPPLIER").text = cfg["supplier_name"]
    ET.SubElement(si, "ITEM_TYPE").text = "product"
    ET.SubElement(si, "UNIT").text = "ks"
    cats = ET.SubElement(si, "CATEGORIES")
    ET.SubElement(cats, "CATEGORY").text = category
    ET.SubElement(cats, "DEFAULT_CATEGORY").text = category
    if data["images"]:
        imgs = ET.SubElement(si, "IMAGES")
        for url in data["images"][:20]:
            ET.SubElement(imgs, "IMAGE").text = url
    ET.SubElement(si, "CODE").text = code
    if re.fullmatch(r"\d{8,14}", data["ean"] or ""):
        ET.SubElement(si, "EAN").text = data["ean"]
    ET.SubElement(si, "CURRENCY").text = "CZK"
    ET.SubElement(si, "VAT").text = fmt_price(vat)
    ET.SubElement(si, "PRICE_VAT").text = fmt_price(price_vat)
    if pricing.get("publish_purchase_price", False) and buy:
        ET.SubElement(si, "PURCHASE_PRICE").text = fmt_price(buy)
    st = ET.SubElement(si, "STOCK")
    ET.SubElement(st, "AMOUNT").text = str(stock)
    report["count"] += 1
    if stock == 0:
        report["out_of_stock"] += 1
    return si


# ---------------------------------------------------------------- celý dodavatel

def load_source(supplier_id: str, cfg: dict, inputs: dict) -> bytes:
    if supplier_id in inputs:
        return Path(inputs[supplier_id]).read_bytes()
    urls = json.loads(os.environ.get("FEED_URLS", "{}") or "{}")
    url = urls.get(supplier_id) or cfg.get("url")
    if not url:
        raise RuntimeError(f"Chybí URL feedu pro '{supplier_id}' (doplňte ji do secretu FEED_URLS).")
    req = urllib.request.Request(url, headers={"User-Agent": "pm-shop-feedy/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def convert_supplier(supplier_id: str, cfg: dict, defaults: dict, inputs: dict) -> dict:
    global NS
    NS = cfg.get("namespaces", {}) or {}
    report = {"count": 0, "out_of_stock": 0, "priced_rrp": 0, "priced_coef": 0,
              "skipped": [], "unmatched": [], "source_items": 0, "kept_missing": 0, "dropped_missing": 0}
    raw = load_source(supplier_id, cfg, inputs)
    root = ET.fromstring(raw)
    item_tag = cfg.get("item_tag", "item")
    items = root.iter(item_tag) if ":" not in item_tag else root.iter(
        "{%s}%s" % (NS[item_tag.split(":")[0]], item_tag.split(":")[1]))
    shop = ET.Element("SHOP")
    seen = set()
    for item in items:
        report["source_items"] += 1
        si = convert_item(item, cfg, defaults, report)
        if si is None:
            continue
        code = si.findtext("CODE")
        if code in seen:
            report["skipped"].append(f"{code} – duplicitní kód ve feedu")
            report["count"] -= 1
            continue
        seen.add(code)
        shop.append(si)

    min_items = int(cfg.get("min_items", defaults.get("min_items", 1)))
    if report["count"] < min_items:
        # ochrana: když dodavatel pošle prázdný/rozbitý feed, starý výstup nepřepisujeme
        raise RuntimeError(f"{supplier_id}: jen {report['count']} produktů (< {min_items}), výstup nepřepisuji.")

    keep_missing(supplier_id, cfg, defaults, shop, seen, report)

    ET.indent(shop, space="  ")
    out = OUT_DIR / f"{supplier_id}.xml"
    xml = ET.tostring(shop, encoding="unicode")
    out.write_text('<?xml version="1.0" encoding="utf-8"?>\n' + xml + "\n", encoding="utf-8")
    write_report(supplier_id, cfg, report)
    return report


def keep_missing(supplier_id: str, cfg: dict, defaults: dict, shop: ET.Element, seen: set, report: dict) -> None:
    """Produkty, které z feedu dodavatele zmizely (vyprodané / vyřazené), necháme ve výstupu
    se skladem 0 – Shoptet je tak označí jako nedostupné. Po keep_missing_days dnech je z výstupu vypustíme."""
    days = int(cfg.get("keep_missing_days", defaults.get("keep_missing_days", 90)))
    old_path = OUT_DIR / f"{supplier_id}.xml"
    state_path = STATE_DIR / f"{supplier_id}.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    today = date.today().isoformat()
    new_state = {}
    if days > 0 and old_path.exists():
        for old in ET.parse(old_path).getroot().findall("SHOPITEM"):
            code = old.findtext("CODE")
            if code in seen:
                continue
            since = state.get(code, today)
            if (date.fromisoformat(today) - date.fromisoformat(since)).days > days:
                report["dropped_missing"] += 1
                continue
            item = deepcopy(old)
            amount = item.find("STOCK/AMOUNT")
            if amount is not None:
                amount.text = "0"
            shop.append(item)
            seen.add(code)
            new_state[code] = since
            report["kept_missing"] += 1
    STATE_DIR.mkdir(exist_ok=True)
    state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def write_report(supplier_id: str, cfg: dict, r: dict) -> None:
    lines = [
        f"Dodavatel: {cfg.get('supplier_name', supplier_id)}",
        f"Položek ve feedu dodavatele: {r['source_items']}",
        f"Produktů ve výstupu: {r['count']} (z toho bez skladu: {r['out_of_stock']})",
        f"Cena z doporučené/prodejní ceny dodavatele: {r['priced_rrp']}, cena z koeficientu: {r['priced_coef']}",
        f"Zmizelo z feedu dodavatele – ponecháno se skladem 0: {r['kept_missing']}, vypuštěno po lhůtě: {r['dropped_missing']}",
        "",
        f"Vyřazené položky ({len(r['skipped'])}):",
        *[f"  - {s}" for s in r["skipped"]],
        "",
        f"Nezařazené do kategorie – spadly do '{cfg.get('fallback_category', 'Ke kontrole')}' ({len(r['unmatched'])}):",
        *[f"  - {s}" for s in r["unmatched"]],
    ]
    (OUT_DIR / f"{supplier_id}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


COMBINED = "vsechny-dodavatele"


def write_combined(config: dict) -> None:
    """Spojí výstupy všech dodavatelů do jednoho feedu.
    Shoptet má limit 8 automatických importů a počet denních aktualizací se sdílí
    mezi všemi importy – jeden společný feed je proto výhodnější.
    Když dodavatel v tomto běhu selhal, použije se jeho poslední platný výstup."""
    shop = ET.Element("SHOP")
    seen = {}
    dup = []
    for sid, cfg in config["suppliers"].items():
        if cfg.get("enabled", True) is False:
            continue
        path = OUT_DIR / f"{sid}.xml"
        if not path.exists():
            continue
        for si in ET.parse(path).getroot().findall("SHOPITEM"):
            code = si.findtext("CODE")
            if code in seen:
                dup.append(f"{code}: {seen[code]} × {sid} (ponechán {seen[code]})")
                continue
            seen[code] = sid
            shop.append(si)
    if not len(shop):
        return
    ET.indent(shop, space="  ")
    (OUT_DIR / f"{COMBINED}.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(shop, encoding="unicode") + "\n",
        encoding="utf-8")
    (OUT_DIR / f"{COMBINED}-report.txt").write_text(
        f"Produktů celkem: {len(shop)}\nStejný kód u více dodavatelů ({len(dup)}):\n"
        + "".join(f"  - {d}\n" for d in dup), encoding="utf-8")


def write_index(config: dict, results: dict) -> None:
    rows = []
    if (OUT_DIR / f"{COMBINED}.xml").exists():
        total = len(ET.parse(OUT_DIR / f"{COMBINED}.xml").getroot())
        rows.append(f"<tr><td><b>Všichni dodavatelé (pro Shoptet)</b></td><td><a href='{COMBINED}.xml'>{COMBINED}.xml</a></td>"
                    f"<td>{total} produktů</td><td><a href='{COMBINED}-report.txt'>report</a></td></tr>")
    for sid, cfg in config["suppliers"].items():
        if cfg.get("enabled", True) is False:
            continue
        res = results.get(sid)
        if isinstance(res, dict):
            status = f"{res['count']} produktů"
        else:
            status = "CHYBA: " + str(res).replace("&", "&amp;").replace("<", "&lt;")
        rows.append(f"<tr><td>{cfg.get('supplier_name', sid)}</td><td><a href='{sid}.xml'>{sid}.xml</a></td>"
                    f"<td>{status}</td><td><a href='{sid}-report.txt'>report</a></td></tr>")
    html = ("<!doctype html><meta charset='utf-8'><title>P+M shop – feedy</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:860px;margin:40px auto;padding:0 16px}"
            "td,th{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}</style>"
            "<h1>P+M shop – převedené feedy pro Shoptet</h1>"
            "<table><tr><th>Dodavatel</th><th>Feed pro Shoptet</th><th>Stav</th><th></th></tr>"
            + "".join(rows) + "</table>")
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "suppliers.yml"))
    ap.add_argument("--input", action="append", default=[], help="id=cesta k lokálnímu XML (pro test)")
    ap.add_argument("--only", action="append", default=[], help="převést jen tohoto dodavatele")
    args = ap.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    defaults = config.get("defaults", {})
    inputs = dict(s.split("=", 1) for s in args.input)
    OUT_DIR.mkdir(exist_ok=True)

    results, failed = {}, 0
    for sid, cfg in config["suppliers"].items():
        if args.only and sid not in args.only:
            continue
        if cfg.get("enabled", True) is False:
            continue
        try:
            r = convert_supplier(sid, cfg, defaults, inputs)
            results[sid] = r
            print(f"OK  {sid}: {r['count']} produktů, vyřazeno {len(r['skipped'])}, "
                  f"nezařazeno {len(r['unmatched'])}")
        except Exception as exc:  # jeden rozbitý dodavatel nesmí shodit ostatní
            failed += 1
            results[sid] = str(exc)
            print(f"ERR {sid}: {exc}", file=sys.stderr)
    if not args.only:
        write_combined(config)
    write_index(config, results)
    # chyby jsou vidět v docs/index.html; stará verze feedu zůstává platná
    return 0


if __name__ == "__main__":
    sys.exit(main())
