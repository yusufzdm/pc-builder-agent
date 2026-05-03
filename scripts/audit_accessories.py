"""
audit_accessories.py
Inventory + components koleksiyonunda kategori-uyumsuz aksesuar/yanlış kategori
kayıtlarını tespit eder. Pattern'ler `database/accessory_filter` modülünde
merkezi tutulur (audit, cleanup, scraper'lar aynı kaynağı kullanır).

SADECE rapor — değişiklik yapmaz.

Çalıştırma:
  python scripts/audit_accessories.py
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db
from database.accessory_filter import is_accessory, ACCESSORY_PATTERNS


def find_accessories():
    db = get_db()
    inv = db["inventory"]
    comp = db["components"]

    findings = defaultdict(list)
    total_per_cat = defaultdict(int)

    for cat in ACCESSORY_PATTERNS:
        if not ACCESSORY_PATTERNS[cat]:
            continue
        all_items = list(inv.find(
            {"component_type": cat},
            {"component_id": 1, "retailer_title": 1, "url": 1, "retailer": 1,
             "price": 1, "in_stock": 1, "is_accessory": 1, "_id": 0}
        ))
        total_per_cat[cat] = len(all_items)
        for item in all_items:
            is_acc, reason = is_accessory(
                retailer_title=item.get("retailer_title"),
                url=item.get("url"),
                component_type=cat,
            )
            if is_acc:
                findings[cat].append({**item, "matched_pattern": reason})

    comp_findings = defaultdict(list)
    for cat in ACCESSORY_PATTERNS:
        if not ACCESSORY_PATTERNS[cat]:
            continue
        for c in comp.find({"component_type": cat}, {"component_id": 1, "name": 1, "_id": 0}):
            is_acc, reason = is_accessory(
                name=c.get("name"),
                component_type=cat,
            )
            if is_acc:
                comp_findings[cat].append({**c, "matched_pattern": reason})

    print("=" * 75)
    print("AKSESUAR / YANLIŞ KATEGORİ TESPİT RAPORU")
    print("=" * 75)

    grand_inv = grand_comp = 0
    for cat in ACCESSORY_PATTERNS:
        if not ACCESSORY_PATTERNS[cat]:
            continue
        inv_hits = findings.get(cat, [])
        comp_hits = comp_findings.get(cat, [])
        grand_inv += len(inv_hits)
        grand_comp += len(comp_hits)
        print(f"\n[{cat.upper()}] inventory: {len(inv_hits)}/{total_per_cat[cat]}, components: {len(comp_hits)}")

        if inv_hits:
            print(f"  --- INVENTORY ÖRNEKLER (ilk 10) ---")
            for it in inv_hits[:10]:
                stock = "✓" if it.get("in_stock") else "✗"
                already = " [already-flagged]" if it.get("is_accessory") else ""
                print(f"  {stock} [{(it.get('retailer') or '?')[:8]}] {(it.get('retailer_title') or '')[:70]:70s}{already}")
                print(f"      -> {it['matched_pattern']}")
            if len(inv_hits) > 10:
                print(f"  ... ve {len(inv_hits) - 10} kayıt daha")

        if comp_hits:
            print(f"  --- COMPONENTS ÖRNEKLER (ilk 5) ---")
            for c in comp_hits[:5]:
                print(f"    {(c.get('name') or '')[:80]}")
                print(f"      -> {c['matched_pattern']}")
            if len(comp_hits) > 5:
                print(f"  ... ve {len(comp_hits) - 5} kayıt daha")

    print("\n" + "=" * 75)
    print(f"TOPLAM: {grand_inv} inventory + {grand_comp} components tespit edildi")
    print("=" * 75)
    return dict(findings), dict(comp_findings)


if __name__ == "__main__":
    find_accessories()
