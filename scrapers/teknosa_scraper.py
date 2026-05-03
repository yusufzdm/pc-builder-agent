"""
scrapers/teknosa_scraper.py

Teknosa kategorilerini hibrit olarak scrape eder:
  - Listing sayfasindan isim/fiyat/url/stok cek
  - DB'de OLMAYAN urunler icin detay sayfasina gir, raw_specs cek
  - Output: scrape_<cat>.json + new_items_<cat>.json

Vatan scraper ile ayni mimari, sadece selector'lar Teknosa'ya gore.

Modlar:
  python scrapers/teknosa_scraper.py --diagnose [--category cpu]
  python scrapers/teknosa_scraper.py --category cpu --max-pages 2
  python scrapers/teknosa_scraper.py [--headless]
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import cloudscraper
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_inventory_collection

# --- AYARLAR ---
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "data" / "teknosa"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.teknosa.com"
RETAILER = "Teknosa"

CATEGORIES = {
    "cpu": "/islemci-c-116001001",
    "motherboard": "/anakart-c-116001002",
    "memory": "/ram-c-116001003",
    "gpu": "/ekran-karti-c-116001004",
    "psu": "/guc-kaynagi-c-116001005",
    "cooler": "/sogutma-sistemi-c-116001006",
    "storage": "/ssd-c-116001008",
    "case": "/bilgisayar-kasasi-c-116001009",
}

# Teknosa urun karti = <ul class="prd"> icindeki <div data-product-*>
CARD_SELECTOR = ".prd"
DATA_DIV_SELECTOR = "[data-product-id]"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def parse_price(text: str) -> int:
    """'12.345,67 TL' -> 12345 (ondaligi at)."""
    if not text:
        return 0
    m = re.search(r'([\d.]+)(?:,\d+)?\s*(?:TL|₺)', text)
    if not m:
        # fallback: tum digitleri al
        digits = "".join(filter(str.isdigit, text))
        return int(digits) if digits else 0
    digits = re.sub(r'[^\d]', '', m.group(1))
    return int(digits) if digits else 0


def first_match(soup, selectors):
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el
    return None


def make_scraper():
    """Cloudflare bypass icin cloudscraper. Selenium yerine HTTP."""
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )


# ============== LISTING SAYFASI PARSE ==============

def parse_listing_card(card) -> dict | None:
    """Teknosa urun karti -> data-product-* attribute'larindan temiz veri al."""
    data_div = card.select_one(DATA_DIV_SELECTOR)
    if not data_div:
        return None

    name = data_div.get("data-product-name", "").strip()
    rel_url = data_div.get("data-product-url", "").strip()
    if not name or not rel_url:
        return None
    url = normalize_url(urljoin(BASE_URL, rel_url))

    # Fiyat: data-product-price (float string) veya data-price-with-discount
    price_str = data_div.get("data-product-price") or data_div.get("data-price-with-discount") or ""
    try:
        price = int(float(price_str)) if price_str else 0
    except (ValueError, TypeError):
        price = 0

    # Stok: data-product-stock attribute Teknosa'da guvenilir degil (hep "N").
    # Fiyat tabanli: pozitif fiyat varsa ve "tukendi" ya da "stokta yok" rozeti yoksa stoktadir.
    in_stock = price > 0
    # Stokta yok rozetini ara
    if in_stock:
        for badge_cls in ["out-of-stock", "tukendi", "stokta-yok", "stockOutBadge"]:
            if card.select_one(f"[class*='{badge_cls}']"):
                in_stock = False
                break

    brand = data_div.get("data-product-brand", "").strip()
    product_id = data_div.get("data-product-id", "").strip()

    return {
        "name": name,
        "brand": brand,
        "price": price,
        "url": url,
        "in_stock": in_stock,
        "teknosa_product_id": product_id,
    }


def scrape_listing(scraper, component_type: str, path: str, max_pages: int | None = None) -> list[dict]:
    target_url_base = urljoin(BASE_URL, path)
    print(f"\n[{component_type.upper()}] listing tarama: {target_url_base}")

    items_by_url: dict[str, dict] = {}
    page = 1
    consecutive_empty = 0

    while True:
        if max_pages and page > max_pages:
            print(f"  > max-pages={max_pages} limitine ulasildi")
            break

        # Teknosa pagination: ?page=N (?s=N sadece ilk 2 sayfada calisiyor!)
        url = f"{target_url_base}?page={page}" if page > 1 else target_url_base
        print(f"  > Sayfa {page} cekiliyor...", end=" ", flush=True)
        try:
            r = scraper.get(url, timeout=30)
            if r.status_code != 200:
                print(f"(status {r.status_code}, durdu)")
                break
        except Exception as e:
            print(f"(hata: {str(e)[:50]})")
            break

        time.sleep(random.uniform(0.8, 1.5))

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select(CARD_SELECTOR)
        if not cards:
            print("(kart yok, kategori bitti)")
            break

        added = 0
        for card in cards:
            data = parse_listing_card(card)
            if not data or not data["url"]:
                continue
            if data["url"] in items_by_url:
                continue
            data["component_type"] = component_type
            data["scraped_at"] = now_iso()
            items_by_url[data["url"]] = data
            added += 1

        print(f"{added} yeni / {len(cards)} kart  (toplam: {len(items_by_url)})")

        if added == 0:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                print("  > Ust uste 2 sayfada yeni urun yok, kategori bitti")
                break
        else:
            consecutive_empty = 0

        page += 1

    print(f"  ✓ {component_type.upper()} listing toplam: {len(items_by_url)} urun")
    return list(items_by_url.values())


# ============== DETAY SAYFASI PARSE ==============

def parse_detail_specs(scraper, url: str) -> dict:
    """Yeni urunlerin detay sayfasindan raw_specs cek."""
    try:
        r = scraper.get(url, timeout=30)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")

        specs = {}
        rows = soup.select(".product-feature-list li") or soup.select(".specifications tr")
        for row in rows:
            cols = row.find_all(["td", "span", "div"])
            if len(cols) >= 2:
                k = cols[0].get_text(strip=True).rstrip(":")
                v = cols[1].get_text(strip=True)
                if k and v:
                    specs[k] = v
        return specs
    except Exception as e:
        return {}


# ============== ANA AKIS ==============

def load_known_urls() -> dict[str, str]:
    inv = get_inventory_collection()
    cursor = inv.find({"retailer": RETAILER}, {"url": 1, "component_id": 1})
    return {normalize_url(d.get("url", "")): d.get("component_id") for d in cursor if d.get("url")}


def diagnose(category: str = "cpu"):
    path = CATEGORIES.get(category)
    if not path:
        print(f"Kategori bulunamadi: {category}")
        return

    print(f"=== DIAGNOSE TEKNOSA: {category} ===")
    scraper = make_scraper()
    url = urljoin(BASE_URL, path)
    print(f"URL: {url}")

    r = scraper.get(url, timeout=30)
    print(f"Status: {r.status_code}, size: {len(r.text)/1000:.0f}K")

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.select(CARD_SELECTOR)
    print(f"\n[CARD] '.prd' -> {len(cards)} kart bulundu")
    if not cards:
        print("Kart yok!")
        return

    print("\n--- ILK 5 KART PARSE ---")
    for i, c in enumerate(cards[:5]):
        data = parse_listing_card(c)
        print(f"[{i}] {json.dumps(data, ensure_ascii=False)}")


def run_scrape(only_category: str | None = None, max_pages: int | None = None,
                fetch_specs_for_new: bool = True):
    known = load_known_urls()
    print(f"DB'deki Teknosa URL sayisi: {len(known)}")

    targets = {only_category: CATEGORIES[only_category]} if only_category else CATEGORIES
    scraper = make_scraper()

    for comp_type, path in targets.items():
        print("\n" + "=" * 60)
        print(f"KATEGORI: {comp_type.upper()}")
        print("=" * 60)

        try:
            listing_items = scrape_listing(scraper, comp_type, path, max_pages=max_pages)

            listing_path = OUTPUT_DIR / f"scrape_{comp_type}.json"
            with open(listing_path, "w", encoding="utf-8") as f:
                json.dump(listing_items, f, ensure_ascii=False, indent=2)
            print(f"  ✓ Listing yazildi: {listing_path.name} ({len(listing_items)} urun)")

            new_items = [it for it in listing_items if it["url"] not in known]
            print(f"  > Yeni urun (DB'de yok): {len(new_items)}")

            if new_items and fetch_specs_for_new:
                print(f"  > Detay sayfalarindan raw_specs cekiliyor...")
                for i, item in enumerate(new_items, 1):
                    print(f"     [{i}/{len(new_items)}] {item['name'][:60]}", end="\r")
                    item["raw_specs"] = parse_detail_specs(scraper, item["url"])
                    item["retailer"] = RETAILER
                    time.sleep(random.uniform(0.3, 0.7))
                print()

            new_path = OUTPUT_DIR / f"new_items_{comp_type}.json"
            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(new_items, f, ensure_ascii=False, indent=2)
            print(f"  ✓ Yeni urunler: {new_path.name} ({len(new_items)} urun)")

        except Exception as e:
            print(f"  ✗ HATA ({comp_type}): {e}")
        # cloudscraper session paylasiliyor — wait gerekmez

    print("\n" + "=" * 60)
    print("TEKNOSA TAMAMLANDI")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--category", help="cpu, motherboard, gpu, ...")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--no-specs", action="store_true")
    args = parser.parse_args()

    if args.diagnose:
        diagnose(args.category or "cpu")
        return

    run_scrape(
        only_category=args.category,
        max_pages=args.max_pages,
        fetch_specs_for_new=not args.no_specs,
    )


if __name__ == "__main__":
    main()
