"""
audit_lp_gpus.py
DB'deki Low Profile (LP) GPU kayıtlarını tespit eder.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db

LP_PATTERNS = [
    " lp ", " lp\\b",
    "low profile", "low-profile",
    "half height", "half-height",
    "hh ", "single slot",
]


def main():
    db = get_db()
    inv = db["inventory"]

    # Tüm GPU kayıtlarını al (in_stock olsun olmasın)
    gpus = list(inv.find(
        {"component_type": "gpu"},
        {"_id": 1, "retailer_title": 1, "url": 1, "retailer": 1, "price": 1, "in_stock": 1}
    ))
    print(f"Toplam GPU inventory: {len(gpus)}")

    hits = []
    for g in gpus:
        title = (g.get("retailer_title") or "").lower()
        url = (g.get("url") or "").lower()
        for pat in LP_PATTERNS:
            # Regex destekli
            import re
            if re.search(pat, title) or re.search(pat, url):
                hits.append({**g, "matched_pattern": pat})
                break

    print(f"\nLow Profile GPU tespit: {len(hits)}\n")
    for h in hits:
        stock = "✓" if h.get("in_stock") else "✗"
        print(f"  {stock} [{h.get('retailer', '?')[:8]}] {h.get('retailer_title', '')[:80]:80s}  ({h.get('price', 0):,} TL)")
        print(f"    pattern: '{h['matched_pattern']}'")


if __name__ == "__main__":
    main()
