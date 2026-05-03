"""
cleanup_er_mismatches.py
ER mismatch tespit edilen inventory kayıtlarını HARD DELETE.
Pattern: components.name ile inventory.retailer_title/url farklı ürün gösteriyor.

Kategoriler:
  - memory: DDR tipi (DDR4 vs DDR5) — link yanlış RAM'e gidiyor
  - psu: wattaj farkı 50W+ — farklı model PSU
  - storage: PCIe gen farkı — farklı performans tier'ı

NEDEN HARD DELETE?
  Bu kayıtlar kullanıcıya yanlış ürün gönderir (link adresinde başka ürün
  satılıyor). Soft tag yetmez — search'ten gizlemek değil, DB'den silmek
  gerek. Geri dönüş: scrape output'larında raw data var, ER pattern
  düzeltilirse tekrar import edilebilir.

Çalıştırma:
  python scripts/cleanup_er_mismatches.py --dry-run
  python scripts/cleanup_er_mismatches.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db
from database.er_validator import validate_er_match


def find_mismatches():
    db = get_db()
    inv = db["inventory"]

    pipeline = [
        {"$lookup": {"from": "components", "localField": "component_id",
                     "foreignField": "component_id", "as": "tech"}},
        {"$unwind": {"path": "$tech", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "component_type": 1, "component_id": 1,
            "retailer": 1, "retailer_title": 1, "url": 1,
            "comp_name": "$tech.name",
        }},
    ]
    mismatches = []
    for r in inv.aggregate(pipeline):
        is_valid, reason = validate_er_match(
            components_name=r.get("comp_name"),
            retailer_title=r.get("retailer_title"),
            url=r.get("url"),
            component_type=r.get("component_type"),
        )
        if not is_valid:
            mismatches.append({**r, "_reason": reason})
    return mismatches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mismatches = find_mismatches()
    if not mismatches:
        print("✅ ER mismatch bulunamadı.")
        return

    by_cat = {}
    for m in mismatches:
        by_cat.setdefault(m.get("component_type", "?"), []).append(m)

    print(f"{'[DRY-RUN] ' if args.dry_run else '[HARD DELETE] '}"
          f"Silinecek toplam: {len(mismatches)} inventory kaydı\n")

    for cat, items in sorted(by_cat.items()):
        print(f"=== {cat.upper()} ({len(items)} kayıt) ===")
        for m in items:
            print(f"  - [{(m.get('retailer') or '?')[:8]}] "
                  f"{(m.get('comp_name') or '')[:60]}")
            print(f"    link → {(m.get('retailer_title') or '')[:60]}")
            print(f"    -> {m['_reason']}")
        print()

    if args.dry_run:
        print("[DRY-RUN] Hiçbir değişiklik yapılmadı.")
        return

    db = get_db()
    inv = db["inventory"]
    ids = [m["_id"] for m in mismatches]
    res = inv.delete_many({"_id": {"$in": ids}})
    print(f"✅ {res.deleted_count} inventory kaydı SİLİNDİ.")


if __name__ == "__main__":
    main()
