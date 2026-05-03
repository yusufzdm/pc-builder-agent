"""
scrapers/vatan_scraper.py

Hibrit scraping: Listing sayfasindan isim/fiyat/url/stok yakalar.
Sadece DB'de OLMAYAN urunler icin detay sayfasina gider (raw_specs cekmek icin).

Modlar:
  python scrapers/vatan_scraper.py --diagnose [--category cpu]
      Ilk sayfayi cek, ilk kartin HTML'ini ve cikan veriyi yazdir, kapan.

  python scrapers/vatan_scraper.py [--category cpu] [--max-pages 3]
      Tum (veya tek) kategoriyi tara, JSON'lari yaz.
      max-pages = test icin sayfa limiti (default: limitsiz).

Cikti:
  scrapers/data/vatan/scrape_<category>.json    (listing'de gorulen tum urunler)
  scrapers/data/vatan/new_items_<category>.json (DB'de olmayan, ER bekleyen urunler)
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

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_inventory_collection

# --- AYARLAR ---
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "data" / "vatan"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.vatanbilgisayar.com"
RETAILER = "Vatan Bilgisayar"

CATEGORIES = {
    "cpu": "islemciler/",
    "motherboard": "anakart/",
    "gpu": "ekran-kartlari/",
    "memory": "bilgisayar-ram-bellek/",
    "storage": "solid-state-disk/",
    "case": "bilgisayar-kasasi/",
    "psu": "guc-kaynaklari-power/",
    "cooler": "sogutma-sistemleri/",
}

# Listing kart selectorleri (oncelik sirasi)
LISTING_SELECTORS = {
    "card": [".product-list", ".product-list-card"],
    "link": ["a.product-list-link", ".product-list__product-name a", "a.product-list__product-name-link"],
    "name": [".product-list__product-name", ".product-list__product-name-link"],
    "price": [".product-list__price", ".product-list__price-current", ".product-price"],
    "out_of_stock_badge": [".product-list__stock-warning", ".btn-stoga-gelince-haber-ver"],
}


# ============== YARDIMCI FONKSIYONLAR ==============

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    """Trailing slash ve fragment temizler."""
    if not url:
        return ""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def parse_price(text: str) -> int:
    """'12.928 TL' -> 12928. Bulamazsa 0."""
    digits = "".join(filter(str.isdigit, text or ""))
    return int(digits) if digits else 0


def first_match(soup, selectors):
    """Verilen selector listesinden ilk bulunan elementi dondurur."""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el
    return None


def make_driver(headless: bool = False):
    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--window-size=1920,1080")
    if headless:
        options.add_argument("--headless=new")
    # version_main: yuklu Chrome ile uyumsuzluk varsa burayi guncelle
    driver = uc.Chrome(options=options, version_main=147, headless=headless)
    return driver


# ============== LISTING SAYFASI PARSE ==============

def parse_listing_card(card, base_url=BASE_URL) -> dict | None:
    """Tek bir urun kartindan (listing'deki) isim, fiyat, url, stok cikarir."""
    # Link
    link_el = first_match(card, LISTING_SELECTORS["link"])
    if not link_el or not link_el.get("href"):
        return None
    url = normalize_url(urljoin(base_url, link_el["href"]))

    # Isim — link'in icindeki text genelde tam ismi verir
    name_el = first_match(card, LISTING_SELECTORS["name"])
    name = (name_el.get_text(strip=True) if name_el else link_el.get_text(strip=True)) or ""

    # Fiyat
    price_el = first_match(card, LISTING_SELECTORS["price"])
    price = parse_price(price_el.get_text() if price_el else "")

    # Stok — "Stoga Gelince Haber Ver" varsa stokta DEGIL
    out_badge = first_match(card, LISTING_SELECTORS["out_of_stock_badge"])
    in_stock = out_badge is None and price > 0

    return {
        "name": name,
        "price": price,
        "url": url,
        "in_stock": in_stock,
    }


def scrape_listing(driver, component_type: str, path: str, max_pages: int | None = None) -> list[dict]:
    """Bir kategorinin tum listing sayfalarini gezer, urun kartlarini toplar."""
    target_url_base = urljoin(BASE_URL, path)
    print(f"\n[{component_type.upper()}] listing tarama: {target_url_base}")

    items_by_url: dict[str, dict] = {}
    page = 1
    consecutive_empty = 0

    while True:
        if max_pages and page > max_pages:
            print(f"  > max-pages={max_pages} limitine ulasildi, durduruluyor.")
            break

        url = f"{target_url_base}?page={page}"
        print(f"  > Sayfa {page} cekiliyor...", end=" ", flush=True)
        driver.get(url)
        time.sleep(random.uniform(2.5, 4.0))

        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = []
        for sel in LISTING_SELECTORS["card"]:
            cards = soup.select(sel)
            if cards:
                break

        if not cards:
            print("(kart yok, kategori bitti)")
            break

        added = 0
        for card in cards:
            data = parse_listing_card(card)
            if not data or not data["url"]:
                continue
            if data["url"] in items_by_url:
                continue  # ayni urun farkli sayfada cikmis (Vatan bazen tekrarliyor)
            data["component_type"] = component_type
            data["scraped_at"] = now_iso()
            items_by_url[data["url"]] = data
            added += 1

        print(f"{added} yeni / {len(cards)} kart  (toplam: {len(items_by_url)})")

        if added == 0:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                print("  > Ust uste 2 sayfada yeni urun yok, kategori bitti.")
                break
        else:
            consecutive_empty = 0

        page += 1

    print(f"  ✓ {component_type.upper()} listing toplam: {len(items_by_url)} urun")
    return list(items_by_url.values())


# ============== DETAY SAYFASI PARSE (sadece yeni urunler icin) ==============

def parse_detail_specs(driver, url: str) -> dict:
    """Yeni bir urunun detay sayfasindan raw_specs cekir."""
    try:
        driver.get(url + "#urun-ozellikleri")
        time.sleep(random.uniform(1.5, 2.5))
        driver.execute_script("window.scrollBy(0, 400);")
        soup = BeautifulSoup(driver.page_source, "html.parser")

        specs = {}
        rows = soup.select(".product-feature tr") or soup.select("#urun-ozellikleri tr")
        for tr in rows:
            cols = tr.find_all("td")
            if len(cols) >= 2:
                k = cols[0].get_text(strip=True).replace(":", "")
                v = cols[1].get_text(strip=True).replace("İzle", "").strip()
                if k and v:
                    specs[k] = v
        return specs
    except Exception as e:
        print(f"     [HATA] detay cekilemedi: {url} -> {e}")
        return {}


# ============== ANA AKIS ==============

def load_known_urls() -> dict[str, str]:
    """MongoDB inventory'den retailer=Vatan olan URL'leri ceker. {url: component_id}"""
    inv = get_inventory_collection()
    cursor = inv.find({"retailer": RETAILER}, {"url": 1, "component_id": 1, "component_type": 1})
    known = {}
    for doc in cursor:
        url = normalize_url(doc.get("url", ""))
        if url:
            known[url] = doc["component_id"]
    return known


def diagnose(category: str = "cpu", headless: bool = False):
    """Selector'larin calistigini dogrulamak icin ilk sayfayi cek, ilk karti yazdir."""
    path = CATEGORIES.get(category)
    if not path:
        print(f"Kategori bulunamadi: {category}")
        return

    print(f"=== DIAGNOSE: {category} ===")
    driver = make_driver(headless=headless)
    try:
        url = urljoin(BASE_URL, path) + "?page=1"
        print(f"URL: {url}")
        driver.get(url)
        time.sleep(4)
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # Card selector denemesi
        for sel in LISTING_SELECTORS["card"]:
            cards = soup.select(sel)
            if cards:
                print(f"\n[CARD] '{sel}' -> {len(cards)} kart bulundu.")
                first = cards[0]
                print("\n--- ILK KART HTML (ilk 2000 char) ---")
                print(first.prettify()[:2000])
                print("\n--- PARSE EDILEN VERI ---")
                data = parse_listing_card(first)
                print(json.dumps(data, ensure_ascii=False, indent=2))
                return
        print("HICBIR card selector eslesmiyor!")
        # Sayfada hangi class'lar var ona bakalim
        print("\nSayfadaki product- ile baslayan class'lar (ilk 30):")
        classes = set()
        for el in soup.find_all(class_=True):
            for c in el.get("class", []):
                if c.startswith("product"):
                    classes.add(c)
        for c in sorted(classes)[:30]:
            print(f"  .{c}")
    finally:
        driver.quit()


def run_scrape(only_category: str | None = None, max_pages: int | None = None, fetch_specs_for_new: bool = True, headless: bool = False):
    """Tum kategorileri (veya tek bir kategoriyi) tarar, JSON ciktilari uretir."""
    known = load_known_urls()
    print(f"DB'deki Vatan URL sayisi: {len(known)}")

    targets = {only_category: CATEGORIES[only_category]} if only_category else CATEGORIES

    for comp_type, path in targets.items():
        print("\n" + "=" * 60)
        print(f"KATEGORI: {comp_type.upper()}")
        print("=" * 60)

        driver = make_driver(headless=headless)
        try:
            listing_items = scrape_listing(driver, comp_type, path, max_pages=max_pages)

            # Listing JSON'u yaz
            listing_path = OUTPUT_DIR / f"scrape_{comp_type}.json"
            with open(listing_path, "w", encoding="utf-8") as f:
                json.dump(listing_items, f, ensure_ascii=False, indent=2)
            print(f"  ✓ Listing yazildi: {listing_path.name} ({len(listing_items)} urun)")

            # Yeni urunleri ayikla
            new_items = [it for it in listing_items if it["url"] not in known]
            print(f"  > Yeni urun (DB'de yok): {len(new_items)}")

            if new_items and fetch_specs_for_new:
                print(f"  > Detay sayfalarindan raw_specs cekiliyor...")
                for i, item in enumerate(new_items, 1):
                    print(f"     [{i}/{len(new_items)}] {item['name'][:60]}", end="\r")
                    item["raw_specs"] = parse_detail_specs(driver, item["url"])
                    item["retailer"] = RETAILER
                print()

            new_path = OUTPUT_DIR / f"new_items_{comp_type}.json"
            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(new_items, f, ensure_ascii=False, indent=2)
            print(f"  ✓ Yeni urunler yazildi: {new_path.name} ({len(new_items)} urun)")

        except Exception as e:
            print(f"  ✗ HATA ({comp_type}): {e}")
        finally:
            driver.quit()
            wait = random.randint(5, 10)
            print(f"  ... bir sonraki kategori icin {wait}s bekleniyor")
            time.sleep(wait)

    print("\n" + "=" * 60)
    print("TUM KATEGORILER TAMAMLANDI")
    print("Sonraki adim: python scrapers/sync_inventory.py")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true", help="Ilk sayfayi cek, selector'lari dogrula")
    parser.add_argument("--category", help="Sadece tek kategori tara (cpu, gpu, memory, ...)")
    parser.add_argument("--max-pages", type=int, default=None, help="Kategori basi maksimum sayfa (test icin)")
    parser.add_argument("--no-specs", action="store_true", help="Yeni urunler icin detay sayfasina girme")
    parser.add_argument("--headless", action="store_true", help="Chrome'u arka planda calistir (background icin gerekli)")
    args = parser.parse_args()

    if args.diagnose:
        diagnose(args.category or "cpu", headless=args.headless)
        return

    run_scrape(
        only_category=args.category,
        max_pages=args.max_pages,
        fetch_specs_for_new=not args.no_specs,
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
