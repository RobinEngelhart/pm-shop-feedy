"""Jednorázový export nákupních cen (bez DPH) pro import do Shoptetu.

Výstup se v GitHub Actions hned zašifruje veřejným klíčem tools/nc_pub.pem,
do veřejného repozitáře se tedy nikdy nedostane čitelná podoba.
Použití: python tools/nakupni_ceny.py vystup.csv
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import convert  # noqa: E402

SUPPLIERS = ["vo-partner", "automotochemie"]   # Bohemia Gifts posílá jen maloobchodní ceny


def main(out_path: str) -> int:
    config = yaml.safe_load((convert.ROOT / "suppliers.yml").read_text(encoding="utf-8"))
    defaults = config.get("defaults", {})
    rows, counts = {}, {}
    for sid in SUPPLIERS:
        cfg = dict(config["suppliers"][sid])
        cfg["pricing"] = {**cfg.get("pricing", {}), "publish_purchase_price": True}
        convert.NS = cfg.get("namespaces", {}) or {}
        report = {"count": 0, "out_of_stock": 0, "priced_rrp": 0, "priced_coef": 0, "skipped": [],
                  "unmatched": [], "source_items": 0, "kept_missing": 0, "dropped_missing": 0, "adult": 0}
        root = ET.fromstring(convert.load_source(sid, cfg, {}))
        n = 0
        for item in root.iter(cfg.get("item_tag", "item")):
            si = convert.convert_item(item, cfg, defaults, report)
            if si is None:
                continue
            code, pp = si.findtext("CODE"), si.findtext("PURCHASE_PRICE")
            if code and pp and code not in rows:
                rows[code] = pp
                n += 1
        counts[sid] = n
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("code;purchasePrice\n")
        for code, pp in rows.items():
            fh.write(f"{code};{pp}\n")
    print("Počty:", counts)   # jen počty, žádné ceny do veřejného logu
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
