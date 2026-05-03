"""
scrapers/hepsiburada_lookup.py

Vatan inventory'sindeki urunleri Hepsiburada'da arar, fiyat + url alir.
Marketplace 'tum kategori scrape' yerine -> kanonik havuz price lookup.

Akis:
  1) MongoDB inventory'den retailer=Vatan urunlerini cek (~917 urun)
  2) Her urun icin /ara?q=<sadelestirilmis isim> ile HB'de ara
  3) Donen ilk 3-5 karttan model kodu (orn '14700K', 'B650M-K', 'RX9070') bazli
     en iyi esleseni sec
  4) Ayni component_id ile inventory'ye ekle (retailer='Hepsiburada')

Modlar:
  python scrapers/hepsiburada_lookup.py --diagnose          (1 urun ile selectorleri test)
  python scrapers/hepsiburada_lookup.py --limit 20          (ilk 20 urun, hizli test)
  python scrapers/hepsiburada_lookup.py                     (tam scan)
  python scrapers/hepsiburada_lookup.py --apply             (matched.json'i DB'ye yaz)
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import os

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_inventory_collection

load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
LLM_MODEL = "gpt-4o-mini"

# --- AYARLAR ---
OUTPUT_DIR = Path(__file__).parent / "data" / "hepsiburada"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://www.hepsiburada.com"
RETAILER = "Hepsiburada"

# Listing kart selectors (oncelik sirasi)
CARD_SELECTORS = [
    "[data-test-id='product-card']",
    "li[class*='productListContent']",
    "[class*='ProductCard']",
]
# Fallback: /p- iceren anchor'lar (HB urun URL'leri /p-XXX formatinda)
FALLBACK_LINK_PATTERN = re.compile(r"/p-")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============== MODEL TOKEN CIKARMA ==============

# Trademark + gereksiz semboller temizligi
TRADEMARK_RE = re.compile(r'[™®©]')

# Model kodu: en az 3 karakter, hem harf hem rakam icermeli (ornek: 14700K, B650M-K, RX9070)
TOKEN_RE = re.compile(r'\b[A-Z0-9][A-Z0-9-]{2,}\b')


def extract_model_tokens(name: str) -> list[str]:
    """Urun isminden SPESIFIK model kodlarini buyuk -> kucuk uzunluk siralayarak dondurur."""
    cleaned = TRADEMARK_RE.sub("", name).upper()
    tokens = TOKEN_RE.findall(cleaned)
    # sadece hem harf hem rakam iceren ve en az 3 char olanlar
    valid = [t for t in tokens if any(c.isalpha() for c in t) and any(c.isdigit() for c in t)]

    # Cok jenerik / kategorik tokenlar -> bunlar tek basina eslesme yetmez
    BLACKLIST = {
        # Bellek tipleri
        "DDR3", "DDR4", "DDR5", "GDDR3", "GDDR4", "GDDR5", "GDDR5X", "GDDR6", "GDDR6X", "GDDR7",
        # USB / PCIe / Form
        "USB3", "USB2", "M2", "PCIE3", "PCIE4", "PCIE5", "PCIE6",
        "GEN3", "GEN4", "GEN5", "ATX", "MATX", "ITX", "EATX",
        # RGB / fan
        "RGB", "ARGB", "RPM", "OEM", "FANLI", "SOGUTUCU",
        # Sunucu RAM
        "1RX8", "2RX8", "1RX4", "2RX4",
        # Memory bus widths
        "32BIT", "64BIT", "96BIT", "128BIT", "192BIT", "256BIT", "384BIT", "512BIT",
        # Capacity (jenerik, ana CPU/GPU/MB modeli icin yetersiz)
        "1GB", "2GB", "4GB", "6GB", "8GB", "10GB", "12GB", "16GB", "20GB", "24GB",
        "32GB", "40GB", "48GB", "64GB", "96GB", "128GB", "192GB", "256GB", "384GB",
        "512GB", "768GB", "1TB", "2TB", "4TB", "8TB",
        # Soketler (CPU/MB icin tek basina yetersiz)
        "AM3", "AM4", "AM5", "AM4+", "STR4", "STR5", "STRX4",
        "LGA1150", "LGA1151", "LGA1155", "LGA1200", "LGA1700", "LGA1851",
        "LGA2011", "LGA2066", "LGA3647", "LGA4189",
        "1700", "1851", "1200", "1151", "1150", "1155", "2011", "2066",
        # Hiz/MHz tokenleri (otomatik olarak da yakalanacak ama emniyet icin)
        "DLSS", "DLSS3", "DLSS4", "FSR", "FSR3", "RAYTRACING",
        # Watt
        "65W", "95W", "105W", "120W", "125W", "150W", "170W", "200W", "250W", "350W",
        "300W", "400W", "500W", "600W", "650W", "700W", "750W", "800W", "850W", "900W",
        "1000W", "1200W", "1500W",
        # CL timings
        "CL14", "CL16", "CL18", "CL19", "CL20", "CL22", "CL24", "CL26", "CL28",
        "CL30", "CL32", "CL34", "CL36", "CL38", "CL40", "CL46", "CL52",
        # Speed (DDR/GDDR)
    }
    # MHZ / GHZ ile biten genel tokenlari da elemek (orn. 8200MHZ, 7600MHZ)
    valid = [t for t in valid
             if t not in BLACKLIST
             and not t.endswith("MHZ")
             and not t.endswith("GHZ")
             and not t.endswith("RPM")
             and not t.endswith("MB")    # 33MB, 36MB cache
             and not t.endswith("NM")]   # 5NM, 7NM, 10NM

    return sorted(set(valid), key=len, reverse=True)


def make_search_query(vatan_name: str) -> str:
    """Hepsiburada aramasi icin sade query olustur. Cok uzun isimler az sonuc verir."""
    cleaned = TRADEMARK_RE.sub("", vatan_name)
    # Marka + model + 1-2 ozellik kafidir
    words = cleaned.split()
    # Ilk 5 kelime
    return " ".join(words[:5])


# ============== HB SAYFA PARSE ==============

def find_cards(soup) -> list:
    """Strateji oncelikleriyle urun kartlarini bul."""
    for sel in CARD_SELECTORS:
        cards = soup.select(sel)
        if cards:
            return cards
    # Fallback: /p- iceren anchor'larin EN UZAK ATA elementi
    cards = []
    seen_hrefs = set()
    for a in soup.find_all("a", href=True):
        if FALLBACK_LINK_PATTERN.search(a["href"]) and a["href"] not in seen_hrefs:
            seen_hrefs.add(a["href"])
            cards.append(a)
    return cards


def parse_card(card) -> dict | None:
    """Tek karttan title + price + url cikar."""
    # URL — kart anchor'sa direkt, degilse icindeki /p- link'i
    url = None
    if card.name == "a" and card.get("href"):
        url = card["href"]
    else:
        a = card.find("a", href=True)
        if a:
            url = a["href"]
    if not url:
        return None
    if not url.startswith("http"):
        url = BASE + url

    # Title — alt attr veya h3 veya span
    title = ""
    img = card.find("img", alt=True)
    if img:
        title = img.get("alt", "").strip()
    if not title:
        h3 = card.find("h3")
        if h3:
            title = h3.get_text(strip=True)
    if not title:
        # link metni
        a = card if card.name == "a" else card.find("a")
        if a:
            title = a.get_text(strip=True)[:200]

    if not title or len(title) < 10:
        return None

    # Fiyat — KESINLIKLE TL veya ₺ icermeli, plain numeric kabul edilmez
    # Once price-spesifik selector dene
    price = 0
    price_el = card.select_one("[data-test-id*='price'], [class*='price' i], [data-bind*='price']")
    if price_el:
        for sub in price_el.find_all(["span", "div"]) + [price_el]:
            txt = sub.get_text(strip=True)
            if ("TL" in txt or "₺" in txt) and len(txt) < 30:
                # ondalik virgul/nokta -> tam sayi
                # Ornek: "12.345,67 TL" -> 12345 (ondaligi at)
                m = re.search(r'([\d.]+)(?:,\d+)?\s*(?:TL|₺)', txt)
                if m:
                    digits = re.sub(r'[^\d]', '', m.group(1))
                    if digits and 50 <= int(digits) <= 1_000_000:
                        price = int(digits)
                        break
    # Fallback: tum span'larda TL ara
    if price == 0:
        for el in card.find_all("span"):
            txt = el.get_text(strip=True)
            if not txt or len(txt) > 30:
                continue
            if "TL" not in txt and "₺" not in txt:
                continue
            m = re.search(r'([\d.]+)(?:,\d+)?\s*(?:TL|₺)', txt)
            if m:
                digits = re.sub(r'[^\d]', '', m.group(1))
                if digits and 50 <= int(digits) <= 1_000_000:
                    price = int(digits)
                    break

    return {"title": title[:200], "price": price, "url": url}


# ============== ESLESME LOJIGI ==============

LLM_VERIFY_SYSTEM = """Iki Turk e-ticaret urun ismini karsilastirip AYNI urun olup olmadigini soyleyeceksin.

FARKLI URUN sayilanlar (red et):
- Marka farki (asus != msi)
- Model serisi/numarasi farki (5070 != 5070 Ti != 5060)
- Form factor farki (B650 != B650M, ATX != mATX != ITX)
- Kapasite farki (1TB != 2TB, 8GB != 16GB VRAM)
- OC vs non-OC etiketi (OC ya iki tarafta da olmali ya iki tarafta da olmamali)
- Renk varyanti farki (WHITE != standart, BLACK != WHITE) — eger isimde renk varsa karsida da olmali
- DDR4 != DDR5 anakart
- Bellek tipi farki (Twin X2 != Twin X3 != Trio)

AYNI URUN sayilanlar (kabul et):
- Marka + model + form factor + kapasite + VRAM + renk + DDR tipi HEPSI ESLESIYOR
- Sadece soket pini gosterimi (1700 vs 1700P), socket spell (AM5 vs Am5), kucuk yazim farkliliklari kabul

CIKTI: SADECE JSON.
{"same_product": true|false, "confidence": 0.0-1.0, "reason": "kisa Turkce"}"""


def llm_verify(vatan_name: str, hb_title: str) -> tuple[bool, float, str]:
    """LLM ile iki urun adinin AYNI urun olup olmadigini dogrula."""
    try:
        resp = openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": LLM_VERIFY_SYSTEM},
                {"role": "user", "content": f"VATAN: {vatan_name}\nHB: {hb_title}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        result = json.loads(resp.choices[0].message.content)
        return (
            bool(result.get("same_product", False)),
            float(result.get("confidence", 0.0)),
            result.get("reason", "")[:200],
        )
    except Exception as e:
        return False, 0.0, f"LLM error: {e}"


def find_best_match(vatan_name: str, candidates: list[dict], use_llm: bool = True,
                     vatan_price: int | None = None) -> dict | None:
    """Aday listesinden en iyi esleseni sec.
    1) Token + marka filtresi -> top adaylar
    2) LLM dogrulama (use_llm=True ise)
    """
    vatan_tokens = extract_model_tokens(vatan_name)
    if not vatan_tokens:
        return None

    vatan_brand = vatan_name.upper().split()[0] if vatan_name else ""

    # Aday adaylari topla: token eslesti AND marka eslesti AND fiyat aklen kabul edilebilir
    pre_matched = []
    for cand in candidates:
        if cand.get("price", 0) <= 0:
            continue
        # Fiyat sanity: HB fiyati Vatan'in 2 katindan fazlaysa abartili satici / yanlis listing
        if vatan_price and vatan_price > 0 and cand["price"] > vatan_price * 2:
            continue
        cand_upper = cand["title"].upper()
        brand_ok = vatan_brand in cand_upper if vatan_brand else False
        # Sadece marka eslesirse devam et — yoksa otomatik red
        if not brand_ok:
            continue
        for token in vatan_tokens:
            if len(token) < 3:
                continue
            if token in cand_upper:
                pre_matched.append({**cand, "matched_token": token, "brand_ok": True})
                break  # her aday icin tek match yeterli

    if not pre_matched:
        return None

    # Fiyata gore sirala (en ucuz once) — yuksek fiyatli "sistem/kit" listing'lerini ele
    pre_matched.sort(key=lambda c: c.get("price", 999_999_999))

    if not use_llm:
        return pre_matched[0]

    # LLM ile her adayi dogrula (ilk 3 ile sinirla)
    for cand in pre_matched[:3]:
        same, conf, reason = llm_verify(vatan_name, cand["title"])
        if same and conf >= 0.8:
            return {**cand, "llm_confidence": conf, "llm_reason": reason}

    return None  # LLM hicbirini onaylamadi


# ============== ANA AKIS ==============

import tempfile
import shutil

_USER_DATA_DIRS: list[Path] = []


def make_driver():
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Her driver kendi user_data_dir'ina sahip olsun -> orphan/cakisma onler
    udd = Path(tempfile.mkdtemp(prefix="hb_uc_"))
    _USER_DATA_DIRS.append(udd)
    options.add_argument(f"--user-data-dir={udd}")
    return uc.Chrome(options=options, version_main=147)


def cleanup_user_data_dirs():
    for udd in _USER_DATA_DIRS:
        try:
            shutil.rmtree(udd, ignore_errors=True)
        except Exception:
            pass


def lookup_one(driver, vatan_name: str, vatan_price: int | None = None) -> tuple[dict | None, list[dict]]:
    """Tek urun icin HB'de ara, en iyi match + ilk 3 adayi dondur."""
    query = make_search_query(vatan_name)
    url = f"{BASE}/ara?q={quote_plus(query)}"
    driver.get(url)
    time.sleep(2.0)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    cards = find_cards(soup)

    candidates = []
    for c in cards[:10]:
        parsed = parse_card(c)
        if parsed:
            candidates.append(parsed)

    best = find_best_match(vatan_name, candidates, vatan_price=vatan_price) if candidates else None
    return best, candidates[:5]


def diagnose():
    """1 urunle test."""
    inv = get_inventory_collection()
    sample = inv.find_one({"retailer": "Vatan Bilgisayar", "component_type": "cpu"})
    if not sample:
        print("Vatan CPU bulunamadi"); return

    name = sample.get("retailer_title", "")
    print(f"Test urun: {name}")
    print(f"Token cikarma: {extract_model_tokens(name)}")
    print(f"Query: '{make_search_query(name)}'")

    driver = make_driver()
    try:
        best, cands = lookup_one(driver, name)
        print(f"\nAday sayisi: {len(cands)}")
        for i, c in enumerate(cands):
            print(f"  [{i}] {c['title'][:80]}  -> {c['price']} TL")
        if best:
            print(f"\n>>> EN IYI ESLESME: {best['title']}")
            print(f"    matched_token: {best['matched_token']}")
            print(f"    price: {best['price']} TL")
            print(f"    url: {best['url']}")
        else:
            print("\n>>> ESLESME YOK")
    finally:
        driver.quit()


def save_progress(matched, no_match):
    with open(OUTPUT_DIR / "matched.json", "w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)
    with open(OUTPUT_DIR / "no_match.json", "w", encoding="utf-8") as f:
        json.dump(no_match, f, ensure_ascii=False, indent=2)


def run_lookup(limit: int | None = None, restart_every: int = 40):
    inv = get_inventory_collection()
    items = list(inv.find(
        {"retailer": "Vatan Bilgisayar"},
        {"_id": 0, "component_id": 1, "retailer_title": 1, "url": 1,
         "component_type": 1, "price": 1, "in_stock": 1},
    ))
    if limit:
        items = items[:limit]
    print(f"Sorgulanacak Vatan urun sayisi: {len(items)}")

    driver = make_driver()
    matched, no_match = [], []
    consecutive_errors = 0
    try:
        for i, item in enumerate(items, 1):
            name = item.get("retailer_title", "")
            if not name:
                continue

            # Her N istekte driver restart (HB session bayatlamasin)
            if i > 1 and (i - 1) % restart_every == 0:
                print(f"   [restart {i}] driver yenileniyor...")
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(2)
                driver = make_driver()

            print(f"[{i}/{len(items)}] {name[:55]}...", end=" ", flush=True)
            try:
                best, top = lookup_one(driver, name, vatan_price=item.get("price"))
                consecutive_errors = 0
                if best:
                    matched.append({
                        "component_id": item["component_id"],
                        "component_type": item["component_type"],
                        "vatan_name": name,
                        "vatan_price": item["price"],
                        "hb_title": best["title"],
                        "hb_price": best["price"],
                        "hb_url": best["url"],
                        "matched_token": best["matched_token"],
                        "brand_ok": best.get("brand_ok"),
                        "scraped_at": now_iso(),
                    })
                    diff = best["price"] - item["price"]
                    sign = "+" if diff >= 0 else ""
                    print(f"✓ {best['price']} TL ({sign}{diff})")
                else:
                    no_match.append({
                        "component_id": item["component_id"],
                        "component_type": item["component_type"],
                        "vatan_name": name,
                        "candidates": top,
                    })
                    print("✗")
            except Exception as e:
                err_msg = str(e)[:80]
                print(f"HATA: {err_msg}")
                no_match.append({
                    "component_id": item["component_id"],
                    "vatan_name": name,
                    "error": str(e)[:200],
                })
                consecutive_errors += 1
                # Pes pese 3 hata -> driver kirik, restart
                if consecutive_errors >= 3:
                    print(f"   [{consecutive_errors} ardisik hata - driver yenileniyor]")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    time.sleep(3)
                    driver = make_driver()
                    consecutive_errors = 0

            if i % 50 == 0:
                save_progress(matched, no_match)
                print(f"   --- progress saved ({len(matched)} matched / {len(no_match)} no match) ---")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        save_progress(matched, no_match)
        cleanup_user_data_dirs()
    print(f"\n=== BITTI === Matched: {len(matched)}   No match: {len(no_match)}")


def apply_matched():
    inv = get_inventory_collection()
    p = OUTPUT_DIR / "matched.json"
    if not p.exists():
        print("matched.json yok"); return
    items = json.load(open(p, encoding="utf-8"))

    count = 0
    for it in items:
        if it.get("hb_price", 0) <= 0:
            continue
        doc = {
            "component_id": it["component_id"],
            "component_type": it["component_type"],
            "retailer": RETAILER,
            "retailer_title": it["hb_title"],
            "url": it["hb_url"],
            "price": it["hb_price"],
            "in_stock": True,
            "last_seen_at": it.get("scraped_at"),
            "_match_token": it.get("matched_token"),
        }
        # URL'i unique key olarak kullan (HB urunleri zaten unique URL'li)
        inv.update_one({"url": it["hb_url"]}, {"$set": doc}, upsert=True)
        count += 1
    print(f"✓ {count} Hepsiburada urunu inventory'ye eklendi")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.diagnose:
        diagnose(); return
    if args.apply:
        apply_matched(); return
    run_lookup(limit=args.limit)


if __name__ == "__main__":
    main()
