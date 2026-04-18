import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import json
import time
import random
import os
from urllib.parse import urljoin
from selenium.webdriver.common.by import By

# --- 2. AŞAMA İÇİN YARDIMCI FONKSİYON ---
def urun_detay_cek(driver, url):
    """Tek bir ürünün sayfasına gider ve detayları çeker."""
    try:
        driver.get(url + "#urun-ozellikleri")
        time.sleep(random.uniform(2, 3.5)) # İnsansı bekleme
        
        # Sayfanın oturması için hafif kaydır
        driver.execute_script("window.scrollBy(0, 300);")
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 1. Ürün Adı
        ad = "Bilinmiyor"
        if soup.title:
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
            "urun_adi": ad,
            "fiyat": fiyat,
            "url": url,
            "ozellikler": detaylar
        }
    except Exception as e:
        print(f"   [HATA] Veri çekilemedi: {url} -> {e}")
        return None

def main():
    # Chrome ayarları
    options = uc.ChromeOptions()
    # options.add_argument('--headless') # Görmek istediğin için kapalı
    driver = uc.Chrome(options=options)
    driver.maximize_window()
    
    base_url = "https://www.vatanbilgisayar.com"
    print(">>> Siteye gidiliyor...")
    driver.get(f"{base_url}/notebook/")
    
    # İlk yükleme için bekle
    time.sleep(5)
    
    print("--- AKILLI TARAMA (SLOW CRAWL) BAŞLATILIYOR ---")
    print("Bu işlem tüm ürünleri (200+) yüklemek için 1-2 dakika sürebilir.")

    last_height = driver.execute_script("return document.body.scrollHeight")
    
    # --- 1. AŞAMA: LİNKLERİ TOPLA (SENİN KODUN) ---
    while True:
        # 1. YAVAŞÇA AŞAĞI İN (Her seferinde 400 piksel)
        for i in range(5):
            driver.execute_script("window.scrollBy(0, 400);")
            time.sleep(0.5)
        
        # 2. Yükleme için bekle
        time.sleep(2)
        
        # 3. Yükseklik değişti mi kontrol et
        new_height = driver.execute_script("return document.body.scrollHeight")
        
        if new_height == last_height:
            print("   > Yükleme duraksadı, tetikleyici aranıyor...")
            try:
                sentinel = driver.find_element(By.ID, "loadMoreSentinel")
                driver.execute_script("arguments[0].scrollIntoView();", sentinel)
                time.sleep(2)
                
                # Bir de "Yukarı-Aşağı" şoklama yapalım
                driver.execute_script("window.scrollBy(0, -500);")
                time.sleep(1)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)
            except:
                pass
            
            # Tekrar kontrol et
            new_height_check = driver.execute_script("return document.body.scrollHeight")
            if new_height_check == last_height:
                print("--- SAYFA SONUNA GELİNDİ (Daha fazla ürün yüklenmiyor) ---")
                break
            else:
                new_height = new_height_check # Devam ediyoruz
        
        last_height = new_height
        
        # Kullanıcıyı bilgilendir
        temp_soup = BeautifulSoup(driver.page_source, 'html.parser')
        products_load_count = len(temp_soup.find_all("div", id="productsLoad"))
        print(f"   > Kaydırma devam ediyor... (Şu an {products_load_count} adet ek paket yüklendi)")

    # --- TOPLAMA AŞAMASI ---
    print("\n--- KAYDIRMA BİTTİ, LİNKLER TOPLANIYOR ---")
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    tum_linkler = set()
    
    # 1. Ana ürünler
    for a in soup.select("#productContainer .product-list-link"):
        if a.get('href'):
            tum_linkler.add(urljoin(base_url, a['href']))
            
    # 2. productsLoad içindeki ürünler
    dinamik_divler = soup.find_all("div", id="productsLoad")
    print(f"[TESPİT] Toplam {len(dinamik_divler)} adet dinamik ürün bloğu bulundu.")
    
    for div in dinamik_divler:
        linkler = div.find_all("a", class_="product-list-link", href=True)
        for a in linkler:
            tum_linkler.add(urljoin(base_url, a['href']))
            
    final_liste = list(tum_linkler)
    print(f"\n[FİNAL SONUÇ] Toplam {len(final_liste)} adet BENZERSİZ laptop linki bulundu.")
    
    # Linkleri Kaydet
    with open('tum_linkler_vatan.json', 'w', encoding='utf-8') as f:
        json.dump(final_liste, f, ensure_ascii=False, indent=4)
    print("Dosya kaydedildi: tum_linkler_vatan.json")

    # ============================================================
    # 2. AŞAMA: DETAYLARI ÇEK (YENİ EKLENEN KISIM)
    # ============================================================
    print("\n" + "="*50)
    print("--- 2. AŞAMA: DETAYLI VERİ ÇEKİMİ BAŞLIYOR ---")
    print("="*50)
    
    detayli_veriler = []
    
    # Dosyadan okuyalım (Garanti olsun)
    with open('tum_linkler_vatan.json', 'r', encoding='utf-8') as f:
        isleme_alinacak_linkler = json.load(f)

    for idx, url in enumerate(isleme_alinacak_linkler, 1):
        print(f"[{idx}/{len(isleme_alinacak_linkler)}] İşleniyor: {url[:60]}...")
        
        veri = urun_detay_cek(driver, url)
        if veri:
            detayli_veriler.append(veri)
        
        # Her 10 üründe bir kaydet (Elektrik kesilirse veri kaybolmasın)
        if idx % 10 == 0:
            with open('vatan_laptoplar_detayli.json', 'w', encoding='utf-8') as f:
                json.dump(detayli_veriler, f, ensure_ascii=False, indent=4)
            print(f"   >>> [OTOKAYIT] {idx} ürün güvenceye alındı.")

    # FİNAL KAYIT
    with open('vatan_laptoplar_detayli.json', 'w', encoding='utf-8') as f:
        json.dump(detayli_veriler, f, ensure_ascii=False, indent=4)

    # Tarayıcıyı güvenli kapat
    try:
        driver.quit()
    except OSError:
        pass 

    print(f"\nİŞLEM TAMAMLANDI! {len(detayli_veriler)} ürün 'vatan_laptoplar_detayli.json' dosyasına kaydedildi.")

if __name__ == "__main__":
    main()
    