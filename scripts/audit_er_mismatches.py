"""
audit_er_mismatches.py
ER pipeline'da components.name ile inventory.retailer_title/url farklı ürün
gösteren kayıtları tespit. Önceki feedback'lerde:
  - PSU: "FSP400-60GHS 400W" (name) vs "FSP SP400-A 350W" (link)
  - RAM: "DDR5-5600" (name) vs "ddr4 pc4-25600" (URL)
  - SSD: "PM951 PCIe 3.0" (name) vs "PM9C1B Gen4" (link)

Audit kategorileri:
  1. RAM: name DDR tipi vs URL/title DDR tipi
  2. Storage: name SSD modeli vs URL'deki model adı
  3. PSU: name wattaj vs URL/title wattaj
"""

import re
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db

db = get_db()
inv = db["inventory"]
comp = db["components"]


def detect_ddr(text: str) -> str | None:
    """name veya url'de DDR tipi tespit et."""
    if not text:
        return None
    t = text.lower()
    # PC4 = DDR4 standardı, PC5 = DDR5
    if re.search(r"\bpc5[-\s]", t) or re.search(r"\bddr5\b", t) or "ddr5-" in t:
        return "DDR5"
    if re.search(r"\bpc4[-\s]", t) or re.search(r"\bddr4\b", t) or "ddr4-" in t:
        return "DDR4"
    if re.search(r"\bpc3[-\s]", t) or re.search(r"\bddr3\b", t) or "ddr3-" in t:
        return "DDR3"
    return None


def detect_psu_wattage(text: str) -> int | None:
    """name veya url'de PSU wattaj tespit et."""
    if not text:
        return None
    m = re.search(r"\b(\d{3,4})\s*w\b", text.lower())
    if m:
        try:
            w = int(m.group(1))
            if 200 <= w <= 2000:
                return w
        except ValueError:
            pass
    return None


def detect_pcie_gen(text: str) -> int | None:
    """SSD için PCIe generation tespit et."""
    if not text:
        return None
    t = text.lower()
    if "pcie 5" in t or "gen5" in t or "5.0 x" in t:
        return 5
    if "pcie 4" in t or "gen4" in t or "4.0 x" in t:
        return 4
    if "pcie 3" in t or "gen3" in t or "3.0 x" in t:
        return 3
    return None


def main():
    print("=" * 75)
    print("ER MISMATCH AUDIT — name ↔ retailer_title/url tutarsızlık")
    print("=" * 75)

    # Inventory'i lookup ile components'e bağla
    pipeline = [
        {"$lookup": {"from": "components", "localField": "component_id",
                     "foreignField": "component_id", "as": "tech"}},
        {"$unwind": {"path": "$tech", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 0, "component_type": 1, "component_id": 1,
            "retailer": 1, "retailer_title": 1, "url": 1,
            "name": "$tech.name",
        }},
    ]
    all_records = list(inv.aggregate(pipeline))
    print(f"Inventory toplam: {len(all_records)} kayıt\n")

    # ─── 1. RAM (memory) — DDR tipi mismatch ───
    print("=" * 75)
    print("[1] MEMORY — components.name DDR tipi vs URL/retailer_title DDR tipi")
    print("=" * 75)
    ram_mismatches = []
    for r in all_records:
        if r.get("component_type") != "memory":
            continue
        name_ddr = detect_ddr(r.get("name") or "")
        title_ddr = detect_ddr(r.get("retailer_title") or "")
        url_ddr = detect_ddr(r.get("url") or "")
        if name_ddr and (title_ddr or url_ddr):
            external_ddr = title_ddr or url_ddr
            if name_ddr != external_ddr:
                ram_mismatches.append({**r, "name_ddr": name_ddr, "external_ddr": external_ddr})
    print(f"  Tespit: {len(ram_mismatches)} kayıt\n")
    for m in ram_mismatches[:10]:
        print(f"  - [{m['retailer'][:8]}]  components.name → {m['name_ddr']}, link → {m['external_ddr']}")
        print(f"    name : {(m.get('name') or '')[:75]}")
        print(f"    title: {(m.get('retailer_title') or '')[:75]}")
        print(f"    url  : {(m.get('url') or '')[:75]}")
        print()

    # ─── 2. PSU — wattaj mismatch ───
    print("=" * 75)
    print("[2] PSU — components.name wattaj vs URL/title wattaj")
    print("=" * 75)
    psu_mismatches = []
    for r in all_records:
        if r.get("component_type") != "psu":
            continue
        name_w = detect_psu_wattage(r.get("name") or "")
        title_w = detect_psu_wattage(r.get("retailer_title") or "")
        url_w = detect_psu_wattage(r.get("url") or "")
        external_w = title_w or url_w
        if name_w and external_w and abs(name_w - external_w) > 50:
            psu_mismatches.append({**r, "name_w": name_w, "external_w": external_w})
    print(f"  Tespit: {len(psu_mismatches)} kayıt (50W+ fark)\n")
    for m in psu_mismatches[:10]:
        print(f"  - [{m['retailer'][:8]}]  name → {m['name_w']}W, link → {m['external_w']}W")
        print(f"    name : {(m.get('name') or '')[:75]}")
        print(f"    title: {(m.get('retailer_title') or '')[:75]}")
        print(f"    url  : {(m.get('url') or '')[:75]}")
        print()

    # ─── 3. Storage — PCIe gen mismatch ───
    print("=" * 75)
    print("[3] STORAGE — components.name PCIe gen vs URL/title PCIe gen")
    print("=" * 75)
    ssd_mismatches = []
    for r in all_records:
        if r.get("component_type") != "storage":
            continue
        name_g = detect_pcie_gen(r.get("name") or "")
        title_g = detect_pcie_gen(r.get("retailer_title") or "")
        url_g = detect_pcie_gen(r.get("url") or "")
        external_g = title_g or url_g
        if name_g and external_g and name_g != external_g:
            ssd_mismatches.append({**r, "name_gen": name_g, "external_gen": external_g})
    print(f"  Tespit: {len(ssd_mismatches)} kayıt\n")
    for m in ssd_mismatches[:10]:
        print(f"  - [{m['retailer'][:8]}]  name → Gen{m['name_gen']}, link → Gen{m['external_gen']}")
        print(f"    name : {(m.get('name') or '')[:75]}")
        print(f"    title: {(m.get('retailer_title') or '')[:75]}")
        print(f"    url  : {(m.get('url') or '')[:75]}")
        print()

    # Özet
    print("=" * 75)
    print(f"TOPLAM MISMATCH: RAM={len(ram_mismatches)}, PSU={len(psu_mismatches)}, "
          f"SSD={len(ssd_mismatches)}")
    print("=" * 75)


if __name__ == "__main__":
    main()
