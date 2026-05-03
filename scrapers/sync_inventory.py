"""
scrapers/sync_inventory.py

Scraper'in urettigi JSON'lari MongoDB inventory'ye uygular.

Akis:
  1) Her kategori icin scrape_<cat>.json oku.
  2) URL bazli match: DB'de varsa price/in_stock/last_seen_at guncelle.
     Fiyat degisti ise last_price_change_at de yaz.
  3) Listing'de gorunmeyenleri (DB'de var ama JSON'da yok) -> in_stock=False isaretle.
  4) Components koleksiyonundaki is_in_stock'u inventory'den turet (drift duzeltme).
  5) new_items_<cat>.json'lardaki urunler entity resolution bekledigi icin DOKUNULMAZ
     — onlari ayri bir pipeline (henuz yok) DB'ye eklemeli.

Modlar:
  python scrapers/sync_inventory.py --dry-run    (degisiklik raporla, DB'ye yazma)
  python scrapers/sync_inventory.py              (uygula)
  python scrapers/sync_inventory.py --category cpu  (tek kategori)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_inventory_collection, get_components_collection

DATA_DIR = Path(__file__).parent / "data" / "vatan"
RETAILER = "Vatan Bilgisayar"
CATEGORIES = ["cpu", "motherboard", "gpu", "memory", "storage", "case", "psu", "cooler"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    if not url:
        return ""
    return url.split("#")[0].split("?")[0].rstrip("/")


def load_scrape_for(category: str) -> list[dict]:
    p = DATA_DIR / f"scrape_{category}.json"
    if not p.exists():
        print(f"  ! {p.name} bulunamadi, atlanir.")
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def sync_category(category: str, dry_run: bool = False) -> dict:
    """Tek kategoriyi sync eder. Sonuc istatistik dict dondurur."""
    inv = get_inventory_collection()
    scraped = load_scrape_for(category)
    if not scraped:
        return {"category": category, "skipped": True}

    scraped_by_url = {normalize_url(it["url"]): it for it in scraped if it.get("url")}

    # DB'deki bu kategori + Vatan urunleri
    db_docs = list(inv.find(
        {"retailer": RETAILER, "component_type": category},
        {"_id": 0, "url": 1, "component_id": 1, "price": 1, "in_stock": 1},
    ))
    db_by_url = {normalize_url(d["url"]): d for d in db_docs if d.get("url")}

    stats = {
        "category": category,
        "scraped": len(scraped_by_url),
        "db_existing": len(db_by_url),
        "matched": 0,
        "price_changed": 0,
        "stock_changed": 0,
        "missing_marked_oos": 0,
        "new_in_listing": 0,
    }

    ts = now_iso()

    # 1) Match edenleri guncelle
    for url, item in scraped_by_url.items():
        if url not in db_by_url:
            stats["new_in_listing"] += 1
            continue

        db_doc = db_by_url[url]
        update = {"last_seen_at": ts, "in_stock": item["in_stock"]}

        old_price = db_doc.get("price", 0)
        new_price = item["price"]
        if new_price > 0 and new_price != old_price:
            update["price"] = new_price
            update["last_price_change_at"] = ts
            stats["price_changed"] += 1

        if db_doc.get("in_stock") != item["in_stock"]:
            stats["stock_changed"] += 1

        stats["matched"] += 1

        if not dry_run:
            inv.update_one({"url": db_doc["url"]}, {"$set": update})

    # 2) Listing'de gorunmeyenleri stok dışı yap
    for url, db_doc in db_by_url.items():
        if url in scraped_by_url:
            continue
        stats["missing_marked_oos"] += 1
        if not dry_run:
            inv.update_one(
                {"url": db_doc["url"]},
                {"$set": {"in_stock": False, "last_seen_at_was_missing": ts}},
            )

    return stats


def sync_components_in_stock(dry_run: bool = False) -> dict:
    """components.is_in_stock'u inventory'den turet. Drift duzeltme."""
    inv = get_inventory_collection()
    comp = get_components_collection()

    in_stock_ids = set(inv.distinct("component_id", {"in_stock": True}))
    print(f"\n[components.is_in_stock sync] inventory'de stokta gorunen unique component_id: {len(in_stock_ids)}")

    if dry_run:
        # Karsilastirma raporu
        currently_true = set(comp.distinct("component_id", {"is_in_stock": True}))
        will_become_true = in_stock_ids - currently_true
        will_become_false = currently_true - in_stock_ids
        print(f"  False -> True olacak: {len(will_become_true)}")
        print(f"  True  -> False olacak: {len(will_become_false)}")
        return {"will_become_true": len(will_become_true), "will_become_false": len(will_become_false)}

    res_true = comp.update_many({"component_id": {"$in": list(in_stock_ids)}}, {"$set": {"is_in_stock": True}})
    res_false = comp.update_many({"component_id": {"$nin": list(in_stock_ids)}}, {"$set": {"is_in_stock": False}})
    print(f"  is_in_stock=True  guncellenen: {res_true.modified_count}")
    print(f"  is_in_stock=False guncellenen: {res_false.modified_count}")
    return {"set_true": res_true.modified_count, "set_false": res_false.modified_count}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--category", help="Sadece tek kategori sync et")
    parser.add_argument("--skip-components-sync", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print(f"INVENTORY SYNC  {'(DRY RUN)' if args.dry_run else '(UYGULA)'}")
    print("=" * 60)

    targets = [args.category] if args.category else CATEGORIES
    summary = []
    for cat in targets:
        print(f"\n--- {cat.upper()} ---")
        s = sync_category(cat, dry_run=args.dry_run)
        if s.get("skipped"):
            continue
        print(f"  scrape: {s['scraped']:>4}  db: {s['db_existing']:>4}  matched: {s['matched']:>4}")
        print(f"  price degisti: {s['price_changed']:>4}  stok degisti: {s['stock_changed']:>4}")
        print(f"  listing'de yok -> stok disi: {s['missing_marked_oos']:>4}")
        print(f"  yeni urun (ER bekliyor):     {s['new_in_listing']:>4}")
        summary.append(s)

    if not args.skip_components_sync:
        sync_components_in_stock(dry_run=args.dry_run)

    print("\n" + "=" * 60)
    print("OZET")
    print("=" * 60)
    total_new = sum(s["new_in_listing"] for s in summary)
    total_oos = sum(s["missing_marked_oos"] for s in summary)
    total_price = sum(s["price_changed"] for s in summary)
    print(f"  Toplam fiyat guncellemesi: {total_price}")
    print(f"  Toplam stok-disi yapilan:  {total_oos}")
    print(f"  ER bekleyen yeni urun:     {total_new}")
    if total_new:
        print(f"  -> new_items_*.json dosyalarini ER pipeline'inda isle.")


if __name__ == "__main__":
    main()
