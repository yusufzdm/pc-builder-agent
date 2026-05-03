"""
scrapers/cleanup_er_junk.py

Mevcut ER output dosyalarindan (matched/review/new) junk urunleri ayikla,
ayri bir <retailer>_<cat>_junk.json'a tasi.

Kullanım:
  python scrapers/cleanup_er_junk.py --retailer teknosa
  python scrapers/cleanup_er_junk.py --retailer teknosa --category cooler
  python scrapers/cleanup_er_junk.py --retailer teknosa --wait  (cooler dosyalari olusana kadar bekle)
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scrapers.entity_resolution import OUTPUT_DIR, CATEGORIES, is_junk


def cleanup_category(retailer: str, category: str) -> dict:
    statuses = ["matched", "review", "new"]
    files = {s: OUTPUT_DIR / f"{retailer}_{category}_{s}.json" for s in statuses}
    if not all(p.exists() for p in files.values()):
        return {"skipped": True}

    all_junk = []
    summary = {}
    for status, p in files.items():
        items = json.load(open(p, encoding="utf-8"))
        keep = [it for it in items if not is_junk(it.get("name", ""))]
        junk = [it for it in items if is_junk(it.get("name", ""))]
        all_junk.extend(junk)
        summary[status] = {"before": len(items), "after": len(keep), "junk": len(junk)}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False, indent=2)

    if all_junk:
        junk_path = OUTPUT_DIR / f"{retailer}_{category}_junk.json"
        with open(junk_path, "w", encoding="utf-8") as f:
            json.dump(all_junk, f, ensure_ascii=False, indent=2)

    summary["total_junk"] = len(all_junk)
    return summary


def wait_for_files(retailer: str, category: str, timeout_sec: int = 10800):
    """Verilen kategori icin matched/review/new dosyalari olusana kadar bekle."""
    files = [OUTPUT_DIR / f"{retailer}_{category}_{s}.json" for s in ["matched", "review", "new"]]
    waited = 0
    while not all(p.exists() for p in files):
        if waited >= timeout_sec:
            print(f"  ! {timeout_sec}s zaman asimi, dosyalar olusmadi")
            return False
        time.sleep(20)
        waited += 20
        print(f"  ... {category} icin bekleniyor ({waited}s)", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retailer", required=True)
    parser.add_argument("--category", help="Sadece tek kategori (varsayilan: hepsi)")
    parser.add_argument("--wait", action="store_true",
                        help="Belirtilen kategori dosyalari olusana kadar bekle")
    args = parser.parse_args()

    targets = [args.category] if args.category else CATEGORIES

    if args.wait:
        if not args.category:
            print("--wait icin --category gerekli")
            sys.exit(1)
        print(f"=== {args.retailer}/{args.category} dosyalari bekleniyor ===")
        if not wait_for_files(args.retailer, args.category):
            sys.exit(1)

    print(f"\n=== JUNK CLEANUP ({args.retailer}) ===")
    grand_junk = 0
    for cat in targets:
        result = cleanup_category(args.retailer, cat)
        if result.get("skipped"):
            print(f"  {cat}: dosyalar yok, atlandi")
            continue
        tj = result["total_junk"]
        grand_junk += tj
        if tj == 0:
            print(f"  {cat}: junk yok")
            continue
        print(f"  {cat}: {tj} junk ayiklandi")
        for status in ["matched", "review", "new"]:
            s = result[status]
            if s["junk"]:
                print(f"      {status}: {s['before']} -> {s['after']} (-{s['junk']})")

    print(f"\n  Toplam ayiklanan junk: {grand_junk}")


if __name__ == "__main__":
    main()
