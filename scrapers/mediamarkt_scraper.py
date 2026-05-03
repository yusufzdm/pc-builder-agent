"""
scrapers/mediamarkt_scraper.py

MediaMarkt Turkiye kategorilerini hibrit olarak scrape eder:
  - Listing sayfasindan isim/fiyat/url/stok cek
  - DB'de OLMAYAN urunler icin detay sayfasina gir, raw_specs cek
  - Output: scrape_<cat>.json + new_items_<cat>.json

Vatan/Teknosa scraper'lari ile ayni mimari, sadece selector'lar MediaMarkt'a gore.

Modlar:
  python scrapers/mediamarkt_scraper.py --diagnose [--category cpu]
  python scrapers/mediamarkt_scraper.py --category cpu --max-pages 2
  python scrapers/mediamarkt_scraper.py [--no-specs]
"""

import argparse
import io
import json
import random
import re
import sys
import time

# Windows cp1252 console -> UTF-8 zorla (Turkce/sembol cikti icin)
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import cloudscraper
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_inventory_collection

# --- AYARLAR ---
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "data" / "mediamarkt"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.mediamarkt.com.tr"
RETAILER = "MediaMarkt"

CATEGORIES = {
    "cpu":         "/tr/category/islemci-679036.html",
    "motherboard": "/tr/category/anakart-798063.html",
    "gpu":         "/tr/category/ekran-karti-679035.html",
    "memory":      "/tr/category/ram-798060.html",
    "storage":     "/tr/category/solid-state-disk-drive-ssd-798099.html",
    "case":        "/tr/category/bilgisayar-kasasi-798061.html",
    "psu":         "/tr/category/guc-kaynagi-power-supply-797541.html",
    "cooler":      "/tr/category/sogutma-sistemleri-90466.html",
}

# MediaMarkt server-side rendered listing kart selectors
# (cesitli data-test attribute'lariyla isaretli; bu degerler 2026 itibariyle gecerli)
CARD_SELECTOR = 'article[data-test="mms-product-card"]'
TITLE_SELECTOR = '[data-test="product-title"]'
# 1P: 'mms-router-link-product-list-item-link'
# 3P/Marketplace: 'mms-router-link-product-list-item-link_mp'
# Image-wrapper link: 'mms-router-link-product-image-wrapper'
LINK_SELECTOR = 'a[data-test^="mms-router-link-product-list-item-link"]'
LINK_FALLBACK_SELECTOR = 'a[data-test="mms-router-link-product-image-wrapper"]'
# Fiyat data-test'i bosluk iceriyor: 'cofr-price product-price'
PRICE_SELECTOR = '[data-test="cofr-price product-price"]'
DELIVERY_SELECTOR = '[data-test="product-delivery"]'

# Brand: MediaMarkt urun isminin ilk kelimesi genelde uppercase marka (AMD, INTEL, ASUS, MSI, ...)
# Listing'de ayri brand alani yok, isimden cikariyoruz.
KNOWN_BRANDS = {
    "AMD", "INTEL", "ASUS", "MSI", "GIGABYTE", "ASROCK", "NVIDIA",
    "CORSAIR", "KINGSTON", "G.SKILL", "GSKILL", "CRUCIAL", "PATRIOT",
    "SAMSUNG", "WD", "WESTERN", "SEAGATE", "TOSHIBA", "SANDISK", "LEXAR",
    "COOLER", "NZXT", "DEEPCOOL", "BE QUIET!", "BEQUIET", "NOCTUA", "ARCTIC",
    "THERMALTAKE", "FRACTAL", "PHANTEKS", "LIAN LI", "LIANLI",
    "SEASONIC", "EVGA", "FSP", "SUPER FLOWER", "XPG", "ADATA", "TEAM",
    "ZALMAN", "AEROCOOL", "SHARKOON", "GAMDIAS", "GAMEPOWER", "POWER BOOST",
    "POWERBOOST", "GIGABYTE", "PNY", "GAINWARD", "PALIT", "INNO3D", "ZOTAC",
    "SAPPHIRE", "POWERCOLOR", "XFX", "BIOSTAR", "COLORFUL",
}


# ============== YARDIMCI FONKSIYONLAR ==============

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def parse_price_from_card(price_text: str) -> int:
    """MediaMarkt fiyat metni: '₺11.999,– ₺11999,00 KDV dahil ...'
    Onceden machine-readable formati ('₺11999,00') hedefliyoruz."""
    if not price_text:
        return 0
    # ilk '₺(rakam),' tum digitleri toplar (binlik nokta dahil)
    m = re.search(r'₺\s*(\d[\d\.]*)\s*,', price_text)
    if m:
        digits = m.group(1).replace('.', '')
        return int(digits) if digits.isdigit() else 0
    # fallback: tum digitleri al
    digits = "".join(filter(str.isdigit, price_text))
    return int(digits) if digits else 0


def guess_brand(name: str) -> str:
    """Urun isminden marka tahmin et. MediaMarkt'ta isim genelde 'BRAND ...' formatinda."""
    if not name:
        return ""
    # ilk 2 kelimeye bak (e.g. 'BE QUIET!', 'COOLER MASTER')
    upper = name.upper()
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if upper.startswith(brand + " ") or upper == brand:
            return brand.title()
    # fallback: ilk kelime tamamen uppercase ise marka say
    parts = name.split()
    if parts and parts[0].isupper() and len(parts[0]) >= 2:
        return parts[0].title()
    return ""


def make_scraper():
    """Cloudflare bypass icin cloudscraper. MediaMarkt React app HTML'i CSR'da render edip
    sunucu tarafi pre-render gonderiyor — JS calistirmaya gerek yok."""
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )


# ============== LISTING SAYFASI PARSE ==============

def parse_listing_card(card) -> dict | None:
    title_el = card.select_one(TITLE_SELECTOR)
    link_el = card.select_one(LINK_SELECTOR) or card.select_one(LINK_FALLBACK_SELECTOR)
    price_el = card.select_one(PRICE_SELECTOR)
    delivery_el = card.select_one(DELIVERY_SELECTOR)

    if not title_el or not link_el:
        return None

    name = title_el.get_text(strip=True)
    rel_url = link_el.get("href", "").strip()
    if not name or not rel_url:
        return None

    url = normalize_url(urljoin(BASE_URL, rel_url))
    price = parse_price_from_card(price_el.get_text(" ", strip=True) if price_el else "")

    # Stok belirleme:
    # - "Adrese teslimata uygun" / "magazada" gibi tahmini teslimat mesaji -> stokta
    # - "Stokta yok" / "tukendi" / "satista degil" -> yok
    # - delivery elementi yoksa fiyata bak
    in_stock = price > 0
    if delivery_el:
        dtxt = delivery_el.get_text(" ", strip=True).lower()
        for neg in ("stokta yok", "tukendi", "tükendi", "satışta değil",
                    "satista degil", "stoga gelince", "şu anda mevcut değil"):
            if neg in dtxt:
                in_stock = False
                break
    # Genel kart icindeki "Stokta Yok" rozetlerini de kontrol et
    if in_stock:
        full_text = card.get_text(" ", strip=True).lower()
        for neg in ("stoga gelince haber ver", "stokta yok"):
            if neg in full_text:
                in_stock = False
                break
    if price <= 0:
        in_stock = False

    brand = guess_brand(name)

    # MediaMarkt urun ID'si URL sonundaki '-<id>.html' kismi
    pid_match = re.search(r'-(\d+)\.html$', rel_url)
    product_id = pid_match.group(1) if pid_match else ""

    return {
        "name": name,
        "brand": brand,
        "price": price,
        "url": url,
        "in_stock": in_stock,
        "mediamarkt_product_id": product_id,
    }


def scrape_listing(scraper, component_type: str, path: str, max_pages: int | None = None) -> list[dict]:
    target_url_base = urljoin(BASE_URL, path)
    print(f"\n[{component_type.upper()}] listing tarama: {target_url_base}")

    items_by_url: dict[str, dict] = {}
    page = 1
    consecutive_no_new = 0

    while True:
        if max_pages and page > max_pages:
            print(f"  > max-pages={max_pages} limitine ulasildi")
            break

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

        # MediaMarkt: gecerli sayfa numarasi yoksa ayni icerigi sunmaya devam ediyor.
        # 2 ust uste hic yeni urun eklenmediyse dur.
        if added == 0:
            consecutive_no_new += 1
            if consecutive_no_new >= 2:
                print("  > Ust uste 2 sayfada yeni urun yok, kategori bitti")
                break
        else:
            consecutive_no_new = 0

        page += 1

    print(f"  ✓ {component_type.upper()} listing toplam: {len(items_by_url)} urun")
    return list(items_by_url.values())


# ============== DETAY SAYFASI PARSE ==============

def parse_detail_specs(scraper, url: str) -> dict:
    """MediaMarkt detail page'inde teknik ozellikler tablosu '<table>' tag'inde
    (ilk table)."""
    try:
        r = scraper.get(url, timeout=30)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")

        specs: dict[str, str] = {}
        # pdp-features-content > table[0]
        table = None
        feat = soup.select_one('[data-test="pdp-features-content"]')
        if feat:
            table = feat.find("table")
        if not table:
            tables = soup.find_all("table")
            table = tables[0] if tables else None
        if not table:
            return {}

        for row in table.select("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                k = cells[0].get_text(strip=True).rstrip(":")
                v = cells[1].get_text(" ", strip=True)
                if k and v:
                    specs[k] = v
        return specs
    except Exception:
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

    print(f"=== DIAGNOSE MEDIAMARKT: {category} ===")
    scraper = make_scraper()
    url = urljoin(BASE_URL, path)
    print(f"URL: {url}")

    r = scraper.get(url, timeout=30)
    print(f"Status: {r.status_code}, size: {len(r.text)/1000:.0f}K")

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.select(CARD_SELECTOR)
    print(f"\n[CARD] '{CARD_SELECTOR}' -> {len(cards)} kart bulundu")
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
    print(f"DB'deki MediaMarkt URL sayisi: {len(known)}")

    targets = {only_category: CATEGORIES[only_category]} if only_category else CATEGORIES
    scraper = make_scraper()

    for comp_type, path in targets.items():
        print("\n" + "=" * 60)
        print(f"KATEGORI: {comp_type.upper()}")
        print("=" * 60)

        try:
            listing_items = scrape_listing(scraper, comp_type, path, max_pages=max_pages)

            # Listing'e retailer ekle
            for it in listing_items:
                it["retailer"] = RETAILER

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
                    time.sleep(random.uniform(0.3, 0.7))
                print()

            new_path = OUTPUT_DIR / f"new_items_{comp_type}.json"
            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(new_items, f, ensure_ascii=False, indent=2)
            print(f"  ✓ Yeni urunler: {new_path.name} ({len(new_items)} urun)")

        except Exception as e:
            print(f"  ✗ HATA ({comp_type}): {e}")

    print("\n" + "=" * 60)
    print("MEDIAMARKT TAMAMLANDI")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--category", help="cpu, motherboard, gpu, memory, storage, case, psu, cooler")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--no-specs", action="store_true")
    parser.add_argument("--headless", action="store_true",
                        help="Vatan/Teknosa pattern uyumu icin (cloudscraper'da etkisiz).")
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
