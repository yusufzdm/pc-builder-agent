"""
cleanup_accessories.py
audit_accessories.py'in tespit ettiği aksesuar/yanlış-kategori kayıtlarını
inventory + components koleksiyonundan SİLER (hard delete). Pattern kaynağı
`database/accessory_filter` modülünden gelir.

NEDEN HARD DELETE?
  Bu kayıtlar PC build için kullanılamaz (kasa standı, kasa fanı, montaj kiti).
  Soft tag (is_accessory=True) DB'de gereksiz şişme yapıyor; ER tarafında
  her seferinde aynı pattern'leri kontrol etmek gerekiyor. Hard delete:
  - DB temiz
  - Yeniden eklenirse helper otomatik filtreleyecek (apply_matched + seed)

GERİ DÖNÜŞ:
  Silinen kayıtlar scraper output'larında (scrapers/data/<retailer>/) hâlâ duruyor.
  Yanlış pozitif tespit edilirse pattern düzeltilip tekrar import edilebilir.

Çalıştırma:
  python scripts/cleanup_accessories.py --dry-run     (önce bunu çalıştır)
  python scripts/cleanup_accessories.py               (hard delete)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db
from database.accessory_filter import is_accessory, ACCESSORY_PATTERNS


def find_accessory_records():
    db = get_db()
    inv = db["inventory"]
    comp = db["components"]

    inv_hits = []
    for cat in ACCESSORY_PATTERNS:
        if not ACCESSORY_PATTERNS[cat]:
            continue
        for item in inv.find({"component_type": cat},
                              {"_id": 1, "retailer_title": 1, "url": 1,
                               "retailer": 1, "component_type": 1, "component_id": 1}):
            is_acc, reason = is_accessory(
                retailer_title=item.get("retailer_title"),
                url=item.get("url"),
                component_type=cat,
            )
            if is_acc:
                inv_hits.append({**item, "_reason": reason})

    comp_hits = []
    for cat in ACCESSORY_PATTERNS:
        if not ACCESSORY_PATTERNS[cat]:
            continue
        for c in comp.find({"component_type": cat},
                            {"_id": 1, "name": 1, "component_type": 1, "component_id": 1}):
            is_acc, reason = is_accessory(name=c.get("name"), component_type=cat)
            if is_acc:
                comp_hits.append({**c, "_reason": reason})

    return inv_hits, comp_hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Sadece silinecekleri yazdır")
    args = parser.parse_args()

    db = get_db()
    inv = db["inventory"]
    comp = db["components"]

    inv_hits, comp_hits = find_accessory_records()
    total = len(inv_hits) + len(comp_hits)
    if total == 0:
        print("✅ Aksesuar bulunamadı, temizlenecek bir şey yok.")
        return

    print(f"{'[DRY-RUN] ' if args.dry_run else '[HARD DELETE] '}"
          f"Silinecek: {len(inv_hits)} inventory + {len(comp_hits)} components\n")

    print("=== INVENTORY ÖRNEKLERİ (ilk 10) ===")
    for h in inv_hits[:10]:
        print(f"  - [{(h.get('retailer') or '?')[:8]}] [{h.get('component_type', '?')}] "
              f"{(h.get('retailer_title') or '')[:65]}")
        print(f"    -> {h['_reason']}")
    if len(inv_hits) > 10:
        print(f"  ... ve {len(inv_hits) - 10} kayıt daha")

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
        i_res = inv.delete_many({"_id": {"$in": inv_ids}})
        print(f"\n✓ Inventory: {i_res.deleted_count} kayıt SİLİNDİ")
    if comp_ids:
        c_res = comp.delete_many({"_id": {"$in": comp_ids}})
        print(f"✓ Components: {c_res.deleted_count} kayıt SİLİNDİ")

    # is_accessory flag'i olan eski kayıtları da temizle (önceki turdaki soft tag'ler)
    legacy_inv = inv.delete_many({"is_accessory": True})
    legacy_comp = comp.delete_many({"is_accessory": True})
    if legacy_inv.deleted_count or legacy_comp.deleted_count:
        print(f"\n[Legacy] is_accessory flag'li {legacy_inv.deleted_count} inventory + "
              f"{legacy_comp.deleted_count} components da silindi.")

    print("\n✅ Tamamlandı.")


if __name__ == "__main__":
    main()
