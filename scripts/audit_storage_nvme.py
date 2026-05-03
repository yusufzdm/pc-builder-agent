"""DB'de NVMe storage durumu — form_factor ve interface field'ları."""
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db

db = get_db()
inv = db["inventory"]

pipeline = [
    {"$match": {"component_type": "storage", "in_stock": True,
                "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}}},
    {"$lookup": {"from": "components", "localField": "component_id",
                 "foreignField": "component_id", "as": "tech"}},
    {"$unwind": "$tech"},
    {"$project": {"_id": 0, "form_factor": "$tech.form_factor",
                  "interface": "$tech.interface", "name": "$tech.name",
                  "price": 1}},
]
results = list(inv.aggregate(pipeline))
print(f"Toplam stokta storage: {len(results)}\n")

# form_factor dağılımı
ff_count = Counter((r.get("form_factor") or "?") for r in results)
print("=== form_factor dağılımı ===")
for ff, c in ff_count.most_common():
    print(f"  {ff:30s}: {c}")

# interface dağılımı
iface_count = Counter((r.get("interface") or "?") for r in results)
print(f"\n=== interface dağılımı ===")
for iface, c in iface_count.most_common(15):
    print(f"  {(iface or 'NULL')[:50]:50s}: {c}")

# M.2 NVMe (M.2 + PCIe interface) — bütçe içinde örnekler
m2_nvme = []
for r in results:
    ff = (r.get("form_factor") or "").lower()
    iface = (r.get("interface") or "").lower()
    if "m.2" in ff and ("pcie" in iface or "nvme" in iface):
        m2_nvme.append(r)

print(f"\n=== M.2 NVMe sayısı: {len(m2_nvme)} ===")
m2_nvme.sort(key=lambda x: x["price"])
print(f"En ucuz 5:")
for r in m2_nvme[:5]:
    print(f"  {r['price']:>7,} TL  {(r.get('name') or '')[:60]}  ({r.get('form_factor')}, {r.get('interface')})")
