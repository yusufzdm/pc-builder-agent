"""
cleanup_laptop_components.py
Laptop bileşenlerini hem inventory hem components koleksiyonunda
`is_laptop: True` flag ile işaretler. Search/optimize_build bu flag'i filtreler.
Hard delete değil — yanlış pozitif olursa --restore ile geri alınabilir.

Çalıştırma:
  python scripts/cleanup_laptop_components.py --dry-run
  python scripts/cleanup_laptop_components.py
  python scripts/cleanup_laptop_components.py --restore
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db
from database.laptop_filter import is_laptop_component


def find_laptop_records():
    db = get_db()
    inv = db["inventory"]
    comp = db["components"]

    inv_hits = []
    for item in inv.find({}, {
        "_id": 1, "retailer_title": 1, "url": 1, "retailer": 1,
        "component_type": 1,
    }):
        is_lap, reason = is_laptop_component(
            retailer_title=item.get("retailer_title"),
            component_type=item.get("component_type"),
        )
        if is_lap:
            inv_hits.append({**item, "_reason": reason})

    comp_hits = []
    for c in comp.find({}, {"_id": 1, "name": 1, "component_type": 1, "form_factor": 1, "memory": 1}):
        ff = c.get("form_factor")
        if c.get("component_type") == "memory":
            mem = c.get("memory") or {}
            if isinstance(mem, dict):
                ff = ff or mem.get("form_factor")
        is_lap, reason = is_laptop_component(
            name=c.get("name"),
            component_type=c.get("component_type"),
            form_factor=ff,
        )
        if is_lap:
            comp_hits.append({**c, "_reason": reason})

    return inv_hits, comp_hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore", action="store_true",
                        help="is_laptop flag'lerini her iki koleksiyondan kaldır")
    args = parser.parse_args()

    db = get_db()
    inv = db["inventory"]
    comp = db["components"]

    if args.restore:
        i_res = inv.update_many({"is_laptop": True}, {"$unset": {"is_laptop": ""}})
        c_res = comp.update_many({"is_laptop": True}, {"$unset": {"is_laptop": ""}})
        print(f"✅ Inventory: {i_res.modified_count}, Components: {c_res.modified_count} kayıttan flag kaldırıldı.")
        return

    inv_hits, comp_hits = find_laptop_records()
    total = len(inv_hits) + len(comp_hits)
    if total == 0:
        print("✅ Laptop bileşeni bulunamadı.")
        return

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Flag'lenecek toplam: "
          f"{len(inv_hits)} inventory + {len(comp_hits)} components\n")

    print("=== INVENTORY ÖRNEKLERİ (ilk 8) ===")
    for h in inv_hits[:8]:
        print(f"  - [{(h.get('retailer') or '?')[:8]}] [{h.get('component_type', '?')}] "
              f"{(h.get('retailer_title') or '')[:65]}")
        print(f"    -> {h['_reason']}")
    if len(inv_hits) > 8:
        print(f"  ... ve {len(inv_hits) - 8} kayıt daha")

    print(f"\n=== COMPONENTS ÖRNEKLERİ (ilk 8) ===")
    for c in comp_hits[:8]:
        print(f"  - [{c.get('component_type', '?')}] {(c.get('name') or '')[:75]}")
        print(f"    -> {c['_reason']}")
    if len(comp_hits) > 8:
        print(f"  ... ve {len(comp_hits) - 8} kayıt daha")

    if args.dry_run:
        print("\n[DRY-RUN] Hiçbir değişiklik yapılmadı.")
        return

    inv_ids = [h["_id"] for h in inv_hits]
    comp_ids = [c["_id"] for c in comp_hits]
    if inv_ids:
        i_res = inv.update_many({"_id": {"$in": inv_ids}}, {"$set": {"is_laptop": True}})
        print(f"\n✓ Inventory: {i_res.modified_count} kayıt is_laptop=True olarak işaretlendi")
    if comp_ids:
        c_res = comp.update_many({"_id": {"$in": comp_ids}}, {"$set": {"is_laptop": True}})
        print(f"✓ Components: {c_res.modified_count} kayıt is_laptop=True olarak işaretlendi")

    print("\n✅ Tamamlandı.")
    print("   Geri almak: python scripts/cleanup_laptop_components.py --restore")


if __name__ == "__main__":
    main()
