"""
audit_ddr5_speeds.py
DDR5 RAM hız dağılımını DB'de kontrol et — chipset cap'leri etkili olabilir mi?
"""

import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db


def main():
    db = get_db()
    inv = db["inventory"]

    pipeline = [
        {"$match": {"component_type": "memory", "in_stock": True, "is_accessory": {"$ne": True}}},
        {"$lookup": {"from": "components", "localField": "component_id",
                     "foreignField": "component_id", "as": "tech"}},
        {"$unwind": "$tech"},
        {"$match": {"tech.ram_type": "DDR5"}},
        {"$project": {"_id": 0, "speed": "$tech.speed", "capacity": "$tech.capacity",
                      "price": 1, "name": "$tech.name"}},
    ]
    rams = list(inv.aggregate(pipeline))
    print(f"Toplam DDR5 RAM (in_stock): {len(rams)}\n")

    speed_dist = Counter(r.get("speed") or 0 for r in rams)
    print("=== Hız dağılımı (MHz) ===")
    for spd, cnt in sorted(speed_dist.items()):
        print(f"  {spd:>5} MHz: {cnt} kayıt")

    # 4800/5600 cap için bütçe içinde 16GB+ kit var mı?
    print("\n=== H610 (cap 4800) için 16GB+ DDR5 kapasiteler ===")
    cap_4800 = [r for r in rams if (r.get("speed") or 0) <= 4800 and (r.get("capacity") or 0) >= 16]
    cap_4800.sort(key=lambda x: x["price"])
    for r in cap_4800[:10]:
        print(f"  {r.get('capacity')} GB / {r.get('speed')} MHz / {r['price']:,} TL  - {r.get('name', '')[:60]}")

    print(f"\n=== B760 (cap 5600) için 16GB+ DDR5 kapasiteler (en ucuz 10) ===")
    cap_5600 = [r for r in rams if (r.get("speed") or 0) <= 5600 and (r.get("capacity") or 0) >= 16]
    cap_5600.sort(key=lambda x: x["price"])
    for r in cap_5600[:10]:
        print(f"  {r.get('capacity')} GB / {r.get('speed')} MHz / {r['price']:,} TL  - {r.get('name', '')[:60]}")


if __name__ == "__main__":
    main()
