"""
verify_mediamarkt_orientation.py
MediaMarkt'ın projeye oryantasyonu tamamlandı mı?
- Aynı component_id altında MediaMarkt + Vatan + Teknosa kayıt var mı?
- Optimize_build sonucunda offers field'ı 3 retailer'ı içeriyor mu?
- Search sonuçlarında retailer_comparison stringi geliyor mu?
"""

import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db
from agents.logic_engine import PCBuilderLogic

logic = PCBuilderLogic()

print("=" * 70)
print("[1] component_id BAŞINA RETAILER SAYISI (kaç ürün multi-retailer?)")
print("=" * 70)

db = get_db()
inv = db["inventory"]

# component_id başına distinct retailer sayısı
pipeline = [
    {"$match": {"in_stock": True, "is_accessory": {"$ne": True},
                "is_laptop": {"$ne": True}}},
    {"$group": {
        "_id": "$component_id",
        "retailers": {"$addToSet": "$retailer"},
        "component_type": {"$first": "$component_type"},
    }},
    {"$project": {
        "retailer_count": {"$size": "$retailers"},
        "retailers": 1, "component_type": 1
    }},
]
results = list(inv.aggregate(pipeline))

count_by_retailers = Counter(r["retailer_count"] for r in results)
print(f"  {'1 retailer':12s}: {count_by_retailers.get(1, 0):>5d} ürün (tek perakendeci)")
print(f"  {'2 retailer':12s}: {count_by_retailers.get(2, 0):>5d} ürün")
print(f"  {'3 retailer':12s}: {count_by_retailers.get(3, 0):>5d} ürün ✓ (tüm 3 perakendeci)")
print(f"  {'TOPLAM':12s}: {len(results):>5d} unique component_id")

# 3-retailer'a sahip ürün örnekleri
multi3 = [r for r in results if r["retailer_count"] == 3][:5]
print(f"\n  3 retailer'a sahip örnekler (ilk 5):")
for r in multi3:
    cid = r["_id"]
    docs = list(inv.find({"component_id": cid}, {"retailer": 1, "price": 1, "retailer_title": 1, "_id": 0}))
    print(f"\n    component_id: {cid[:60]}")
    for d in docs:
        print(f"      [{d['retailer']:18s}] {d['price']:>6,} TL  {(d.get('retailer_title') or '')[:50]}")

# 2-retailer örnekleri
multi2 = [r for r in results if r["retailer_count"] == 2][:3]
print(f"\n  2 retailer'a sahip örnekler (ilk 3):")
for r in multi2:
    cid = r["_id"]
    docs = list(inv.find({"component_id": cid}, {"retailer": 1, "price": 1, "_id": 0}))
    retailers = sorted({d["retailer"] for d in docs})
    print(f"    {cid[:55]:55s} ({', '.join(retailers)})")

print()
print("=" * 70)
print("[2] OPTIMIZE_BUILD — gaming 50K, offers field doluyor mu?")
print("=" * 70)

build = logic.optimize_build(50000, "gaming")
parts = build.get("selected_components", {})
multi_retailer_count = 0
for cat, p in parts.items():
    if not isinstance(p, dict):
        continue
    offers = p.get("offers") or []
    distinct = sorted({o.get("retailer") for o in offers if o.get("retailer")})
    name = p.get("name", "?")[:50]
    print(f"\n  [{cat}] {name}")
    if len(distinct) >= 2:
        multi_retailer_count += 1
        print(f"    OFFERS ({len(distinct)} retailer):")
        seen = set()
        for o in sorted(offers, key=lambda x: x.get("price", 0)):
            if o["retailer"] in seen:
                continue
            seen.add(o["retailer"])
            print(f"      [{o['retailer']:18s}] {o['price']:>6,} TL  {o.get('url', '')[:50]}")
    else:
        print(f"    Tek retailer: {p.get('retailer', '?')} {p.get('price', 0):,} TL")

print(f"\n  Multi-retailer parça sayısı: {multi_retailer_count} / {len(parts)}")
