import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import json
import time
import random
import os
from urllib.parse import urljoin
from selenium.webdriver.common.by import By

# --- AYARLAR ---
# Kayıt yerini scriptin olduğu klasöre göre sabitleyelim
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "data/vatan")

CATEGORIES = {
    "memory": "bilgisayar-ram-bellek/",
    "storage": "solid-state-disk/",
    "case": "bilgisayar-kasasi/",
    "psu": "guc-kaynaklari-power/",
    "cooler": "sogutma-sistemleri/"
}

BASE_URL = "https://www.vatanbilgisayar.com"

# Klasörü oluştur
os.makedirs(OUTPUT_DIR, exist_ok=True)

def urun_detay_cek(driver, url, component_type):
    """Tek bir ürünün sayfasına gider ve detayları çeker."""
    try:
        driver.get(url + "#urun-ozellikleri")
        time.sleep(random.uniform(1.5, 2.5))
        
        driver.execute_script("window.scrollBy(0, 400);")
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 1. Ürün Adı
        ad = "Bilinmiyor"
        title_tag = soup.find("h1", class_="product-list__product-name")
        if title_tag:
            ad = title_tag.get_text(strip=True)
        elif soup.title:
            ad = soup.title.string.split("-")[0].strip()
        
        # 2. Fiyat
        fiyat = 0
        fiyat_tag = soup.find("span", class_="product-list__price") or soup.find("div", class_="product-price")
        if fiyat_tag:
            ham_fiyat = "".join(filter(str.isdigit, fiyat_tag.get_text()))
            if ham_fiyat:
                fiyat = int(ham_fiyat)

        # 3. Teknik Özellikler
        detaylar = {}
        tablo = soup.select(".product-feature tr") or soup.select("#urun-ozellikleri tr")
        
        for satir in tablo:
            cols = satir.find_all("td")
            if len(cols) >= 2:
                baslik = cols[0].get_text(strip=True).replace(":", "")
                deger = cols[1].get_text(strip=True).replace("İzle", "").strip()
                if baslik and deger:
                    detaylar[baslik] = deger
                
        return {
            "name": ad,
            "price": fiyat,
            "url": url,
            "component_type": component_type,
            "raw_specs": detaylar,
            "retailer": "Vatan Bilgisayar",
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        print(f"   [HATA] Detay çekilemedi: {url} -> {e}")
        return None

def kategori_tara(driver, component_type, path):
    """Sayfalama (Pagination) kullanarak tüm ürünleri bulur."""
    target_url_base = urljoin(BASE_URL, path)
    print(f"\n📂 Kategori Başlatıldı: {component_type.upper()}")
    
    linkler = set()
    page = 1
    
    print("--- SAYFALAMA MODU AKTİF (Garantici Yöntem) ---")
    while True:
        current_url = f"{target_url_base}?page={page}"
        print(f"   > Sayfa {page} taranıyor...", end="\r")
        
        driver.get(current_url)
        time.sleep(random.uniform(2.5, 4.0)) # Sayfanın yüklenmesi için bekle
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        page_links = [urljoin(BASE_URL, a['href']) for a in soup.select(".product-list-link") if a.get('href')]
        
        if not page_links:
            # Eğer sayfada hiç ürün linki yoksa kategori bitmiştir
            print(f"\n   --- TARAMA BİTTİ. {page-1} sayfa gezildi, toplam {len(linkler)} ürün bulundu. ---")
            break
            
        # Bazı durumlarda Vatan son sayfadan sonra tekrar 1. sayfayı gösterebilir.
        # Bunu engellemek için yeni link gelip gelmediğine bakalım.
        prev_count = len(linkler)
        linkler.update(page_links)
        
        if len(linkler) == prev_count:
            print(f"\n   --- TARAMA BİTTİ (Yeni ürün gelmiyor). Toplam {len(linkler)} ürün. ---")
            break
            
        print(f"   > Sayfa {page}: {len(page_links)} ürün yakalandı. (Toplam: {len(linkler)})", end="\r")
        page += 1

    if len(linkler) == 0:
        print(f"   ⚠️ UYARI: {component_type} kategorisinde hiç ürün bulunamadı!")
        return

    # 3. Aşama: Detayları Çek
    print(f"\n   🚀 Detaylı veri çekimi başlıyor ({len(linkler)} ürün)...")
    kategori_verileri = []
    kategori_verileri = []
    for idx, url in enumerate(list(linkler), 1):
        print(f"     [{idx}/{len(linkler)}] {url[:50]}...", end="\r")
        veri = urun_detay_cek(driver, url, component_type)
        if veri:
            kategori_verileri.append(veri)
        
        # Her 20 üründe bir ara kayıt
        if idx % 20 == 0:
            with open(f"{OUTPUT_DIR}/{component_type}_vatan.json", "w", encoding="utf-8") as f:
                json.dump(kategori_verileri, f, ensure_ascii=False, indent=4)

    # Final Kayıt
    with open(f"{OUTPUT_DIR}/{component_type}_vatan.json", "w", encoding="utf-8") as f:
        json.dump(kategori_verileri, f, ensure_ascii=False, indent=4)
    print(f"\n   ✅ {len(kategori_verileri)} ürün kaydedildi: {component_type}_vatan.json")

def main():
    # Kategori listesini kopyalayalım ki döngüde hata olmasın
    for comp_type, path in CATEGORIES.items():
        print(f"\n" + "="*60)
        print(f"🚀 YENİ OTURUM BAŞLATILIYOR: {comp_type.upper()}")
        print("="*60)
        
        options = uc.ChromeOptions()
        # options.add_argument('--headless')
        driver = uc.Chrome(options=options)
        driver.maximize_window()

        try:
            kategori_tara(driver, comp_type, path)
            print(f"\n✅ {comp_type.upper()} başarıyla tamamlandı.")
        except Exception as e:
            print(f"\n❌ {comp_type.upper()} kategorisinde KRİTİK HATA: {e}")
        finally:
            driver.quit()
            # Kategoriler arası insansı bekleme
            wait_time = random.randint(5, 12)
            print(f"\n💤 Bir sonraki kategori için {wait_time} saniye bekleniyor...")
            time.sleep(wait_time)

    print("\n🎉 TÜM KATEGORİLER TAMAMLANDI!")

if __name__ == "__main__":
    main()
