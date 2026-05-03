"""
audit_cooler_misclassified.py
Cooler kategorisinde gerçekte kasa fanı / aksesuar olan kayıtları tespit.
Kullanıcı feedback'i: "Cougar AQUA Water 120mm" diye seçilmiş ama link
"Cougar Vortex VX120 ... kasa fani" → gerçekte chassis fan.
"""

import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db

CHASSIS_FAN_PATTERNS = [
    r"\bkasa\s*fan",
    r"\bchassis\s*fan",
    r"\bcase\s*fan",
    r"\b120mm\s+fan(?!\w)",      # "120mm fan" ama "120mm fanli" değil
    r"\b140mm\s+fan(?!\w)",
    r"\bargb\s*fan(?!\w)",       # Standalone RGB fan
    r"\bsystem\s*fan",
    r"\bvortex\b",                # Cougar Vortex serisi = kasa fanı
    r"\bsickleflow\b",            # Cooler Master SickleFlow = kasa fanı
    r"\bnoctua\s+nf-",            # Noctua NF- serisi (NF-A12, NF-S12) = kasa fanı
    r"\bcorsair\s+(?:ll|sp|ml|af|ql|hd)\d{2,3}",  # Corsair fan serileri
]

def main():
    db = get_db()
    inv = db["inventory"]
    comp = db["components"]

    # Tüm cooler inventory + components.height var mı?
    inv_total = inv.count_documents({"component_type": "cooler"})
    comp_total = comp.count_documents({"component_type": "cooler"})
    print(f"Cooler inventory toplam: {inv_total}")
    print(f"Cooler components toplam: {comp_total}\n")

    # Inventory'de pattern eşleşen kayıtlar
    print("=" * 75)
    print("[INVENTORY] Cooler kategorisinde kasa fanı şüphesi")
    print("=" * 75)

    inv_hits = []
    for item in inv.find({"component_type": "cooler"},
                         {"_id": 0, "retailer_title": 1, "url": 1, "retailer": 1,
                          "in_stock": 1, "component_id": 1}):
        title = (item.get("retailer_title") or "").lower()
        url = (item.get("url") or "").lower()
        for pat in CHASSIS_FAN_PATTERNS:
            if re.search(pat, title, re.IGNORECASE) or re.search(pat, url, re.IGNORECASE):
                inv_hits.append({**item, "_pat": pat})
                break

    print(f"Tespit: {len(inv_hits)}/{inv_total}\n")
    for h in inv_hits[:15]:
        stock = "✓" if h.get("in_stock") else "✗"
        print(f"  {stock} [{h.get('retailer', '?')[:8]}] {(h.get('retailer_title') or '')[:75]}")
        print(f"     pattern: {h['_pat']}")
    if len(inv_hits) > 15:
        print(f"  ... ve {len(inv_hits) - 15} kayıt daha")

    # Components height field var mı?
    print("\n" + "=" * 75)
    print("[COMPONENTS] Cooler kategorisinde height dağılımı")
    print("=" * 75)

    height_buckets = {"None": 0, "<50mm": 0, "50-100mm": 0, "100-150mm": 0, "150+": 0}
    samples_by_bucket = {k: [] for k in height_buckets}
    for c in comp.find({"component_type": "cooler"}, {"_id": 0, "name": 1, "height": 1}):
        h = c.get("height")
        name = c.get("name", "?")
        if h is None:
            bucket = "None"
        else:
            try:
                hv = int(h)
                if hv < 50:
                    bucket = "<50mm"
                elif hv < 100:
                    bucket = "50-100mm"
                elif hv < 150:
                    bucket = "100-150mm"
                else:
                    bucket = "150+"
            except (TypeError, ValueError):
                bucket = "None"
        height_buckets[bucket] += 1
        if len(samples_by_bucket[bucket]) < 3:
            samples_by_bucket[bucket].append((name[:60], h))

    for bucket, n in height_buckets.items():
        print(f"  {bucket:>10s}: {n:>5d} kayıt")
        for name, h in samples_by_bucket[bucket][:2]:
            print(f"      - {name}  (height={h})")

    # height < 50mm OLAN gerçek CPU cooler var mı? (false positive risk)
    print(f"\n[height<50mm AMA gerçek cooler şüphesi] inceleme:")
    low_h = list(comp.find({"component_type": "cooler", "height": {"$lt": 50, "$gt": 0}},
                            {"_id": 0, "name": 1, "height": 1}).limit(20))
    for c in low_h:
        print(f"  - height={c.get('height')}mm  {c.get('name', '')[:70]}")


if __name__ == "__main__":
    main()
