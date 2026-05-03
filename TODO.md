# PC Builder Agent - TODO & Hata Takip Listesi

## Feedback (Dış Kaynaklı Hakem Bulguları — AÇIK)

- [ ] **PSU isim ↔ link tutarsız (ER mismatch):** Build çıktısında bir PSU'nun adı "FSP Group FSP400-60GHS(85)-R SFX 400W 80+ Bronze" iken Teknosa linki "FSP Performance SP400-A 350W"a (farklı model, farklı wattaj, sertifikasız) gidiyor. `entity_resolution.py` iki farklı PSU'yu aynı `component_id`'ye eşlemiş. Çözüm: PSU eşleşmesinde wattaj+form factor+sertifika doğrulaması ekle, ER'ı yeniden çalıştır. Kaynak: harici Claude review (2026-05-03). Süre: ~yarım gün.

- [ ] **NVMe yerine SATA SSD seçimi — perf kaybı:** 55K bütçede 6,069 TL'lik KIOXIA EXCERIA SATA 2.5" (555 MB/s) seçildi, anakartın iki M.2 NVMe slotu boş kaldı. Aynı parayla 1 TB Gen3 NVMe (3000+ MB/s) alınabilir. Çözüm: `optimize_build`'de MB'nin `m2_slots` doluysa storage seçimi NVMe-first iki kademeli (önce M.2 NVMe, fallback SATA). Use case'e göre tercih (gaming/render/architecture/design'da NVMe zorunlu). Kaynak: harici Claude review (2026-05-03). Süre: ~30 dk.

- [ ] **Cooler ↔ CPU Socket uyumsuzluğu (KRİTİK):** Office_15k senaryosunda Intel Celeron G5900 (LGA1200) seçildi, soğutucu olarak AMD Wraith Stealth Socket AM4 atandı — soket uyumsuz, fiziksel takılmaz. `optimize_build`'in cooler seçimi soket-aware değil. Çözüm: cooler seçiminde CPU socket'e göre filtre (cooler.compatible_sockets list'i kontrol edilmeli, yoksa name-bazlı: "AM4"/"AM5"/"LGA1700"/"LGA1200" pattern'leri). Validator'da KONTROL 9 olarak da eklenebilir. Kaynak: MediaMarkt entegrasyonu sonrası tespit (2026-05-03). Süre: ~30 dk.

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

- [x] **MediaMarkt entegrasyonu (2026-05-03):** `scrapers/mediamarkt_scraper.py` (cloudscraper ile, 8 kategori, 1118 ürün scrape). `entity_resolution.py` MediaMarkt yapılandırması (RETAILER_DIRS + RETAILER_NAME_MAP). LLM matching → 879 matched, apply'da junk/aksesuar/laptop pre-filter sonrası 875 ürün DB'ye yazıldı. ER eşleşmesi: 192 ürün (3-retailer), 419 ürün (2-retailer). Inventory toplam: 3,188 kayıt (Teknosa 1253 + Vatan 1060 + MediaMarkt 875). Multi-retailer karşılaştırma optimize_build'de otomatik çalışıyor.
- [x] **Feedback — SODIMM / laptop bileşenleri temizlendi (2026-05-03):** "Tasarım 55K" senaryosunda Kingston KVR48S40BS8 (laptop SODIMM) masaüstüne seçilmişti. `database/laptop_filter.py` merkezi helper (Intel U/H/HX/HS, AMD U/HS/HX, Mobile GPU, mSATA, SODIMM part-number regex'leri — 30+ pattern). Audit + cleanup (7 inventory + 149 components flag'lendi). `seed_database.py` ve `entity_resolution.py:apply_matched`'te otomatik mekanizma — yeni eklemelerde laptop bileşenleri SKIP. Test: 17/17 case geçti, 6 doğrulama tüm senaryolarda UDIMM seçildi.
- [x] **Feedback — Cooler kasa fanı (ER mismatch) çözüldü (2026-05-03):** `database/accessory_filter.py` merkezi helper (URL pattern + bağlam-aware). Kasa fanı pattern'i + URL `kasa-fan` desteği + `COOLER_CONTEXT_NEGATIVE` (cooler/sıvı/AIO/tower geçen ürünler false positive değil). 19 kayıt **HARD DELETE** (10 kasa standı + 7 yeni kasa fanı + 2 montaj kiti). `entity_resolution.py` 3 katmanlı filter: process_category pre-filter, apply_matched defensive, accessory_filter merkezi. Validator KONTROL 8 (cooler title + bağlam yoksa ⛔ error). Apply'da 4 ek kasa fanı atlandı.
- [x] **Feedback — Use case "iş" partial match + design profili (2026-05-03):** `main.py:extract_info_from_messages` regex word-boundary'li listeye dönüştü. Yeni anchor'lar: tasarım/photoshop/figma/illustrator → design; premiere/blender/after effects → rendering; autocad/revit → architecture; muhasebe/word/excel → office. `\biş\b` partial fix + `'iş yeri/bilgisayarı'` phrase. Yeni `"design"` ALLOCATION_PROFILE + `gpu_boost_params["design"]` + `GPU_HEAVY_USE_CASES` constant. Test: 17/17 case geçti, 55K tasarım senaryosu artık RTX 5050 + 32GB RAM + NVMe seçiyor.
- [x] **Feedback — Kasa standları ve aksesuarlar temizlendi (2026-05-03):** Harici Claude review "Tower 600 Light-Year Green" linkinin gerçekte kasa standı olduğunu yakaladı. 12 aksesuar (10 kasa standı + 2 cooler montaj kiti) `is_accessory: True` flag'lendi (sonradan hard delete'e çevrildi).
- [x] **Feedback — RAM hızı chipset capi (2026-05-03):** DDR5-6000 modül H610 chipset'te JEDEC 4800'de çalışıyor — fazla ödenen para. `CHIPSET_MAX_RAM_SPEED` tablosu (30+ Intel/AMD chipset) eklendi; `_select_best_ram` artık chipset cap'ini uyguluyor. Gaming_50k'da 11,269 → 8,999 TL (~%20 tasarruf), Architecture_45k'da 1k tasarruf.
- [x] **Feedback — LP GPU + mid-tower filtresi (2026-05-03):** Mid-tower kasada Low Profile GPU seçimi mantıksız (RTX 3050 LP 96-bit vs normal 128-bit). `LP_GPU_REGEX` ile gaming/rendering/architecture'da floor + upgrade + rebalance + tools.search_gpu seviyelerinde filter.
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
