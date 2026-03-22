# PC Builder Agent - TODO & Hata Takip Listesi 📝

Bu dosya, proje geliştirme sürecinde tespit edilen ve çözülmesi gereken teknik borçları/hataları takip etmek içindir.

### 🔴 Kritik Hatalar & Düzeltmeler
- [ ] **Eksik Yeni Nesil Verisi:** RTX 5000 ve Intel Core Ultra serisi kütüphanede (24k veri) yok. `tuckerandrew21/pc-part-dataset` fork'undan çekilip sisteme yamalanmalı.
- [ ] **Normalizer Kategori Uyuşmazlığı:** RAM (`ram`), Kasa (`pccase`) ve Soğutucu (`cpucooler`) isimleri veritabanı ile eşleşmediği için Normalizer bu kategorileri atlıyor. Fixlenmeli.
- [ ] **Bütçe Dağılım Hatası:** `optimize_build` fonksiyonu bazen RAM veya Kasa bütçesini ekran kartına aktararak eksik parçalı sistem topluyor. "Eksiksiz parça" kısıtı (hard constraint) güçlendirilmeli.

### 🟡 Gelecek Özellikler
- [ ] **Çoklu Perakendeci:** İtopya ve Sinerji için scraper ve entegrasyon süreçleri başlatılmalı.
- [ ] **FPS Tahmini:** Seçilen donanımların oyunlardaki performansını tahmin eden bir tool/algoritma eklenmeli.
- [ ] **Web UI Geliştirme:** Streamlit arayüzüne "Sistem Özeti" ve "Tıklanabilir Sepet" detayları eklenmeli.

### 🟢 Tamamlananlar
- [x] **Vatan Scraper:** 1.200+ ürün gerçek fiyat ve linkleriyle çekildi.
- [x] **Entity Resolution:** Vatan ürünlerini Referans Kütüphanesi ile eşleştiren sistem kuruldu.
- [x] **Vector Search:** Filtreleme destekli anlamsal arama aktif edildi.
- [x] **GitHub Entegrasyonu:** Proje `v2-agentic-rag` dalına taşındı.
