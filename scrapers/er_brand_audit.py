"""
scrapers/er_brand_audit.py

ER matched dosyalarini tara: retailer listing'in markasi ile reference component'in
metadata.manufacturer'i uyusmuyorsa eslesmeyi marka_uyumsuz olarak ayikla.

Akis:
  1) Her matched item icin retailer_title'in basindan marka cikar
  2) component_id ile components.metadata.manufacturer cek
  3) Normalize + alias kontrolu ile karsilastir
  4) Uyumsuzlari brand_mismatch.json'a tasi + inventory'den sil

Mod:
  python scrapers/er_brand_audit.py --retailer all --dry-run   (sadece tespit)
  python scrapers/er_brand_audit.py --retailer all              (uygula)
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_components_collection, get_inventory_collection

OUTPUT_DIR = Path(__file__).parent / "data" / "er"
CATEGORIES = ["cpu", "motherboard", "gpu", "memory", "storage", "case", "psu", "cooler"]

# Cok kelimeli marka adlari — ilk kelimeyi degil tum bunlari yakala
KNOWN_MULTIWORD_BRANDS = [
    "cooler master", "be quiet", "lian li", "g.skill", "g skill",
    "western digital", "silicon power", "silver stone", "silverstone",
    "in win", "team group", "fractal design", "high power", "power boost",
]

# Marka alias'lari (alt-marka -> ust marka)
# Ust marka = veritabaninda metadata.manufacturer'a yazilan
# Alt markalar = perakendeci listing'inde gecebilir
ALIASES = {
    "asus": {"rog", "tuf", "prime", "proart", "dual", "strix"},
    "msi": {"meg", "mag", "mpg", "mortar", "tomahawk"},
    "gigabyte": {"aorus", "windforce", "eagle"},
    "asrock": {"phantomgaming", "phantom", "steellegend", "taichi"},
    "gskill": {"ripjaws", "ripjawsv", "trident", "tridentz", "aegis", "flarex", "neo"},
    "coolermaster": {"masterair", "masterliquid", "hyper", "mwe"},
    "thermaltake": {"toughpower", "smart", "tough"},
    "corsair": {"vengeance", "dominator", "rm", "cv", "tx"},
    "kingston": {"fury", "hyperx", "kc", "kc600", "nv2", "beast"},
    "seagate": {"barracuda", "ironwolf", "firecuda"},
    "wd": {"westerndigital", "blue", "black", "red", "purple"},
    "westerndigital": {"wd", "blue", "black", "red", "purple"},
    "samsung": {"evo", "qvo", "pro"},
    "crucial": {"ballistix"},
    "adata": {"xpg"},
    "xpg": {"adata"},
    "deepcool": {"gammaxx", "ag"},
    "thermalright": {"assassin", "peerless", "frost"},
    "noctua": {"nh"},
    "bequiet": {"darkrock", "purerock", "shadowrock", "purepower"},
    "powerboost": {"highpower"},
    "highpower": {"powerboost"},
}


def normalize(s: str) -> str:
    return re.sub(r"[^\w]", "", (s or "").lower())


def extract_brand(name: str) -> str:
    """Listing adindan marka cikarir. Cok kelimeli markalar oncelikli."""
    n = (name or "").lower().strip()
    for mw in KNOWN_MULTIWORD_BRANDS:
        if n.startswith(mw):
            return mw.replace(" ", "").replace(".", "")
    parts = re.split(r"[\s\-]+", n)
    return normalize(parts[0]) if parts else ""


def brands_match(rt_brand: str, ref_brand: str) -> bool:
    rb = normalize(rt_brand)
    rf = normalize(ref_brand)
    if not rb or not rf:
        return True  # bilgi eksik -> tolere et (false alarm yapmayalim)
    if rb == rf:
        return True
    # icerme: "asus" in "asusrog", "rog" in "asusrog"
    if rb in rf or rf in rb:
        return True
    # alias karsilastirmasi
    for parent, kids in ALIASES.items():
        if (rb == parent and rf in kids) or (rf == parent and rb in kids):
            return True
        if rb in kids and rf in kids:
            return True
    return False


def load_manufacturer_cache():
    comp = get_components_collection()
    cache = {}
    for c in comp.find({}, {"component_id": 1, "metadata.manufacturer": 1}):
        if c.get("component_id"):
            cache[c["component_id"]] = (c.get("metadata") or {}).get("manufacturer", "")
    return cache


def audit_retailer(retailer: str, dry_run: bool = False):
    print(f"\n=== AUDIT: {retailer} (dry_run={dry_run}) ===")
    print("  components manufacturer cache yukleniyor...")
    manuf = load_manufacturer_cache()
    print(f"    {len(manuf)} component cachelendi")

    inv = get_inventory_collection()
    total_mm = 0
    all_mm_samples = []
    cat_summary = {}

    for cat in CATEGORIES:
        path = OUTPUT_DIR / f"{retailer}_{cat}_matched.json"
        if not path.exists():
            continue
        items = json.load(open(path, encoding="utf-8"))
        keep = []
        mismatch = []

        for it in items:
            cid = (it.get("_er") or {}).get("component_id")
            if not cid:
                keep.append(it)
                continue
            ref_brand = manuf.get(cid, "")
            rt_brand = extract_brand(it.get("name", ""))
            if brands_match(rt_brand, ref_brand):
                keep.append(it)
            else:
                it["_brand_mismatch"] = {
                    "retailer_brand": rt_brand,
                    "reference_brand": ref_brand,
                }
                mismatch.append(it)

        cat_summary[cat] = {"matched_before": len(items), "mismatch": len(mismatch)}
        total_mm += len(mismatch)

        # Ornek topla
        for it in mismatch[:3]:
            all_mm_samples.append((cat, it))

        if mismatch and not dry_run:
            # matched -> filtrelenmis
            with open(path, "w", encoding="utf-8") as f:
                json.dump(keep, f, ensure_ascii=False, indent=2)
            # brand_mismatch.json'a tasi
            bm_path = OUTPUT_DIR / f"{retailer}_{cat}_brand_mismatch.json"
            existing = []
            if bm_path.exists():
                existing = json.load(open(bm_path, encoding="utf-8"))
            existing.extend(mismatch)
            with open(bm_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            # inventory'den sil
            urls = [it["url"] for it in mismatch if it.get("url")]
            if urls:
                inv.delete_many({"url": {"$in": urls}})

    # Ozet
    print(f"\n  Kategori bazinda:")
    print(f"  {'kategori':<14} {'matched':>9} {'mismatch':>10} {'%':>6}")
    for cat, s in cat_summary.items():
        m = s["matched_before"]
        mm = s["mismatch"]
        pct = mm * 100 / m if m else 0
        flag = " <-- bak" if pct > 5 else ""
        print(f"  {cat:<14} {m:>9} {mm:>10} {pct:>5.1f}%{flag}")
    print(f"  TOPLAM uyumsuz: {total_mm}")

    print(f"\n  ORNEKLER (ilk 10):")
    for cat, it in all_mm_samples[:10]:
        bm = it["_brand_mismatch"]
        print(f"    [{cat}] retailer={bm['retailer_brand']:<14} ref={bm['reference_brand']:<14} | {it['name'][:65]}")

    if not dry_run and total_mm > 0:
        print(f"\n  ✓ {total_mm} uyumsuz inventory'den silindi, brand_mismatch.json'lara tasindi.")

    return total_mm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retailer", default="all", choices=["all", "vatan", "teknosa"])
    parser.add_argument("--dry-run", action="store_true",
                        help="Sadece tespit et, dosya/inventory degisiklik yapma")
    args = parser.parse_args()

    retailers = ["vatan", "teknosa"] if args.retailer == "all" else [args.retailer]
    grand_total = 0
    for r in retailers:
        grand_total += audit_retailer(r, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"GENEL TOPLAM marka-uyumsuz: {grand_total}")
    if args.dry_run:
        print("(dry-run modu: degisiklik yapilmadi)")


if __name__ == "__main__":
    main()
