# PC Builder Agent - TODO & Hata Takip Listesi

## Kritik Hatalar

- [ ] **Entity Resolution marka uyumsuzluklari (145 urun):** Farkli marka urunler birbiriyle eslestirilmis (EVGA->EVEREST, Gigabyte->RAMPAGE vs.). Kullanici yanlis URL'ye yonlendiriliyor. Toplu temizlik gerekiyor.
- [ ] **Entity Resolution model uyumsuzluklari:** Ayni marka ama farkli model eslesmeler var (IRDM PRO vs IRDM X, UX200 vs UX100). Daha ince kontrol gerekli.

## Orta Oncelik

- [ ] **Validator proaktif upgrade maliyeti (logic_engine.py:ValidatorNode):** Her tool response'unda `get_best_part_for_budget` cagiriyor -> ekstra OpenAI embedding API call + MongoDB query. Yavaslatici ve maliyetli.
- [ ] **300K+ butce verimsizligi:** Envanterdeki en pahali parcalar ~200K'da doygunluga ulasiyor. 300K ve 500K ayni sistemi topluyor (%65 ve %39 verimlilik). Daha pahali GPU/MB eklenmeli veya kullaniciya uyari verilmeli.
- [ ] **DDR5 platform secimi:** Yuksek butcelerde DDR5 platformuna gecis daha agresif olmali. Simdilik DDR4'e kilitleniyor.
- [ ] **Chat gecmisi kirpma:** GPT-4o-mini 128K context dolunca API hata veriyor. Token kirpma mekanizmasi eklenmeli.

## Gelecek Ozellikler

- [ ] **Coklu Perakendeci:** Itopya ve Sinerji icin scraper ve entegrasyon.
- [ ] **FPS Tahmini:** Secilen donaniminin oyunlardaki performansini tahmin eden tool.
- [ ] **Web UI:** Streamlit arayuzune "Sistem Ozeti" ve "Tiklanabilir Sepet" eklenmeli.

## Tamamlananlar

- [x] **CATEGORY_MAP duzeltmesi:** `storage`->`"storage"`, `cooler`->`"cooler"` olarak duzeltildi.
- [x] **BuildCores alan yapisi uyumu:** Uyumluluk kontrolleri dogru nested alanlara bakiyor (`specifications.tdp`, `memory.ram_type` vs.).
- [x] **DDR RAM uyumsuzlugu cozuldu:** `_filter_ram_by_type` strict yapildi, `_ram_pipeline` aggregation ile components.ram_type ve capacity field'lari kullaniliyor. Isimden parse etme kaldirildi.
- [x] **Floor + Weighted Remainder butce algoritmasi:** Taban fiyat + agirlikli dagilim + greedy upgrade. 30K-200K arasi uyumlu build uretiyor.
- [x] **Onay dongusu duzeltildi:** System prompt'a acik onay akisi eklendi. "Onayladim" sonrasi tekrar sormak yasaklandi.
- [x] **Sahte siparis tamamlama engellendi:** System prompt'a "siparis yetenegin YOK" uyarisi eklendi.
- [x] **Validator sonuclari kullaniciya gosteriliyor:** main.py'de errors/warnings ekrana yazdiriliyor.
- [x] **Use-case bazli minimum RAM uyarisi:** optimize_build sonunda yetersiz RAM kapasitesi icin uyari donuyor.
- [x] **Retailer title link uyumu:** System prompt'a retailer_title kullanim talimatı eklendi.
- [x] **Vatan Scraper:** 1286 urun gercek fiyat ve linkleriyle cekildi.
- [x] **Entity Resolution:** Vatan urunleri referans kutuphanesiyle eslesti. 928/1286 (%72) temiz eslesme.
- [x] **Vector Search:** Filtreleme destekli anlamsal arama aktif.
- [x] **Kategori ismi duzeltmesi:** MongoDB'de `pccase`->`case`, `cpucooler`->`cooler`, `ram`->`memory` olarak guncellendi.
- [x] **is_in_stock senkronizasyonu:** Inventory ile components arasinda esitlendi.
- [x] **62 yeni component eklendi:** 9 CPU, 13 GPU, 40 MB BuildCores'tan embedding ile yuklendi.
- [x] **Yanlis eslesmeler temizlendi:** Portable SSD, kasa fani, notebook RAM gibi hatali eslesmeler silindi.
- [x] **Proje yapisi duzeltildi:** `C:\pc-builder-agent\` konumuna tasindi.
