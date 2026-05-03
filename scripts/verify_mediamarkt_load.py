"""verify_mediamarkt_load.py — DB'deki MediaMarkt kayıtlarını sayar."""
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db

db = get_db()
inv = db["inventory"]

retailer_counts = Counter()
mm_by_cat = Counter()
for d in inv.find({}, {"retailer": 1, "component_type": 1, "_id": 0}):
    r = d.get("retailer") or "?"
    retailer_counts[r] += 1
    if r == "MediaMarkt":
        mm_by_cat[d.get("component_type", "?")] += 1

print("=== Inventory retailer dağılımı ===")
for r, c in retailer_counts.most_common():
    print(f"  {r:20s}: {c:>5d} kayıt")

print(f"\n=== MediaMarkt kategori dağılımı ===")
for cat, c in sorted(mm_by_cat.items()):
    print(f"  {cat:12s}: {c:>4d} kayıt")
print(f"  TOPLAM     : {sum(mm_by_cat.values())} kayıt")

# is_laptop / is_accessory flag durumu
mm_lap = inv.count_documents({"retailer": "MediaMarkt", "is_laptop": True})
mm_acc = inv.count_documents({"retailer": "MediaMarkt", "is_accessory": True})
print(f"\nMediaMarkt is_laptop=True: {mm_lap}  (beklenen: 0 — pre-filter eledi)")
print(f"MediaMarkt is_accessory=True: {mm_acc}  (beklenen: 0 — defensive filter sildi/skip)")
