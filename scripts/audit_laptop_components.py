"""
audit_laptop_components.py
DB'deki tüm inventory + components kayıtlarını laptop_filter.is_laptop_component
ile tarar, raporlar. SADECE rapor — değişiklik yapmaz.

Çalıştırma:
  python scripts/audit_laptop_components.py
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db
from database.laptop_filter import is_laptop_component


def main():
    db = get_db()
    inv = db["inventory"]
    comp = db["components"]

    # Kategori başına inventory hits
    inv_hits = defaultdict(list)
    inv_total = defaultdict(int)

    for item in inv.find({}, {
        "_id": 1, "retailer_title": 1, "url": 1, "retailer": 1,
        "price": 1, "in_stock": 1, "component_type": 1, "component_id": 1,
        "is_accessory": 1, "is_laptop": 1,
    }):
        cat = item.get("component_type") or "?"
        inv_total[cat] += 1
        is_lap, reason = is_laptop_component(
            retailer_title=item.get("retailer_title"),
            component_type=cat,
        )
        if is_lap:
            inv_hits[cat].append({**item, "_reason": reason})

    # Components tarafı (form_factor da kullanılabilir)
    comp_hits = defaultdict(list)
    comp_total = defaultdict(int)
    for c in comp.find({}, {"_id": 0, "name": 1, "component_type": 1, "form_factor": 1, "memory": 1}):
        cat = c.get("component_type") or "?"
        comp_total[cat] += 1
        # Memory için form_factor field'ı doğrudan kullanılabilir
        ff = c.get("form_factor")
        if cat == "memory":
            mem = c.get("memory") or {}
            # components'te memory bazen alt obje
            if isinstance(mem, dict):
                ff = ff or mem.get("form_factor")
        is_lap, reason = is_laptop_component(
            name=c.get("name"),
            component_type=cat,
            form_factor=ff,
        )
        if is_lap:
            comp_hits[cat].append({**c, "_reason": reason})

    # Rapor
    print("=" * 75)
    print("LAPTOP BİLEŞENİ TESPİT RAPORU")
    print("=" * 75)
    print(f"{'Kategori':12s} | {'Inventory':>10s} | {'Components':>10s}")
    print("-" * 75)

    cats = sorted(set(list(inv_total.keys()) + list(comp_total.keys())))
    grand_inv = grand_comp = 0
    for cat in cats:
        ih = len(inv_hits.get(cat, []))
        ch = len(comp_hits.get(cat, []))
        grand_inv += ih
        grand_comp += ch
        total_i = inv_total.get(cat, 0)
        total_c = comp_total.get(cat, 0)
        print(f"{cat:12s} | {ih:>4d} / {total_i:>4d} | {ch:>4d} / {total_c:>4d}")

    print("-" * 75)
    print(f"{'TOPLAM':12s} | {grand_inv:>10d} | {grand_comp:>10d}")
    print()

    # Kategori başına ilk 8 örnek
    for cat in cats:
        ih = inv_hits.get(cat, [])
        ch = comp_hits.get(cat, [])
        if not ih and not ch:
            continue
        print(f"\n[{cat.upper()}] inventory: {len(ih)}, components: {len(ch)}")
        if ih:
            print(f"  --- INVENTORY ÖRNEKLERİ ---")
            for h in ih[:8]:
                stock = "✓" if h.get("in_stock") else "✗"
                acc = " (accessory)" if h.get("is_accessory") else ""
                lap = " (already-flagged)" if h.get("is_laptop") else ""
                print(f"    {stock} [{(h.get('retailer') or '?')[:8]}] {(h.get('retailer_title') or '')[:65]:65s}")
                print(f"        reason: {h['_reason']}{acc}{lap}")
            if len(ih) > 8:
                print(f"    ... ve {len(ih) - 8} kayıt daha")

        if ch:
            print(f"  --- COMPONENTS ÖRNEKLERİ ---")
            for c in ch[:5]:
                print(f"    {(c.get('name') or '')[:75]}")
                print(f"        reason: {c['_reason']}")
            if len(ch) > 5:
                print(f"    ... ve {len(ch) - 5} kayıt daha")


if __name__ == "__main__":
    main()
