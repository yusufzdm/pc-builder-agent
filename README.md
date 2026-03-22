# PC Builder Agent 🖥️ 🚀

Türkçe doğal dil desteği ile çalışan, **Nöro-Sembolik (Neuro-Symbolic)** mimariye sahip, karmaşık yapılandırma görevlerini (Constraint Satisfaction Problem) çözen akıllı bir PC toplama asistanı.

## 📌 Proje Vizyonu ve Teorik Altyapı

Bu proje, yapay zeka alanında salt üretken modellerden (Generative AI) nöro-sembolik mimarilere geçişin bir örneğidir. PC toplama alanı; katı donanım uyumluluk kuralları (soket tipleri, güç gereksinimleri, fiziksel boyutlar) ve kapsamlı bileşen bağımlılıkları nedeniyle bu tür sistemler için ideal bir problem uzayı sunar.

### 🧠 Nöro-Sembolik Yaklaşım
- **LLM (Nöral Katman):** Doğal dil anlama, kullanıcı niyetini kavrama ve bulanık eşleşme (fuzzy matching) yapar.
- **Mantık Motoru (Sembolik Katman):** Donanım dünyasının "sert" kısıtlamalarını (CSP - Constraint Satisfaction Problem) deterministik algoritmalarla denetler. Halüsinasyonu %0'a indirir.

---

## 🎯 Temel Özellikler

- **Doğal Dil Desteği:** "30k'ya oyun için bir PC topla" veya "Elimdeki i7-4770'e uygun anakart bul" gibi karmaşık komutları anlar.
- **Teknik Uyumluluk Garantisi:** Soket tipi (LGA1700, AM5 vb.), RAM tipi (DDR4/DDR5), PSU gücü (Watt) ve fiziksel boyut (Kasa/GPU uzunluğu) kontrolü.
- **Hibrit Arama (Agentic RAG):** MongoDB Atlas Vector Search kullanarak 24.000+ donanım parçası arasından hem anlamsal hem de teknik filtreli arama yapar.
- **Kendi Kendine Düzeltme (Self-Correction):** Eğer ajan uyumsuz bir parça seçerse, sistem hatayı otomatik algılar ve ajana geri bildirim vererek düzelttirir.
- **Hafıza Yönetimi:** LangGraph sayesinde konuşma geçmişini ve yapılandırılmış sistem durumunu (State) paralel olarak yönetir.

---

## 🏗️ Mimari Yapı (LangGraph & DCG)

Proje, konuşmayı bir istem-cevap döngüsü olarak değil, bir **Yönlendirilmiş Döngüsel Grafik (Directed Cyclic Graph - DCG)** olarak modeller.

1.  **Chatbot Node:** Kullanıcı niyetini analiz eder, araçları çağırır veya cevap üretir.
2.  **BudgetAwareToolNode:** LLM'in bütçe parametrelerini unuttuğu durumlarda state'ten otomatik enjeksiyon yaparak güvenli arama sağlar.
3.  **Validator Node:** `logic_engine.py` üzerinden seçilen parçaları CSP prensiplerine göre denetler.
4.  **Araştırma Modu (Research Mode):** Stokta olmayan veya legacy (eski) parçalar için 24k dökümanlık referans kütüphanesini tarar.

### Veri Akış Şeması
```
Kullanıcı → LangGraph (Orkestratör) → LLM (GPT-4o) 
                                         ↓
                [Araçlar] ←→ [MongoDB Atlas Vector Search]
                                         ↓
                [Validator] ←→ [Logic Engine (CSP Solver)]
```

---

## 📊 Veri Stratejisi

Sistem, verileri iki ana koldan yönetir (Decoupled Architecture):

1.  **Referans Kütüphanesi (`components`):** 24.262 dökümanlık, tüm teknik detayları (TDP, Boyut, Soket) içeren "Source of Truth" (Doğruluk Kaynağı).
2.  **Envanter (`inventory`):** Perakendecilerden gelen (şu an mock) fiyat ve stok bilgisini barındıran katman.

Arama motoru, bu iki koleksiyonu `component_id` üzerinden dinamik olarak birleştirir (JOIN).

---

## 🚀 Kurulum ve Çalıştırma

### Bağımlılıklar
```bash
pip install langchain langchain-openai langgraph pymongo openai python-dotenv streamlit duckduckgo-search
```

### Ortam Değişkenleri (.env)
```env
OPENAI_API_KEY=sk-...
MONGO_URI=mongodb+srv://...
MONGO_DB_NAME=buildcores_db
```

### Çalıştırma
- **Terminal:** `cd pc-builder-agent && python main.py`
- **Web UI:** `streamlit run pc-builder-agent/ui.py`

---

## 🛠️ Mevcut Durum ve Yol Haritası (Roadmap)

### 🟢 Tamamlananlar
- [x] **MongoDB & Vector Search:** 24k dökümanlı kütüphane ve Atlas Vector Search entegrasyonu.
- [x] **Kategori Standardizasyonu:** Tüm sistem `component_type` alanına geçirildi.
- [x] **Gelişmiş Filtreleme:** Soket, RAM tipi ve Watt bazlı teknik aramalar aktif.
- [x] **Legacy Desteği:** Kullanıcının elindeki eski parçaları tanıma yeteneği (`search_reference_library`).
- [x] **LangGraph Stabilizasyonu:** Sonsuz döngü ve boş yanıt hataları giderildi.
- [x] **Perakendeci Scraper:** Vatan Bilgisayar'dan dinamik ürün kazıma sistemi (Hybrid Scroller) yazıldı ve 1.200+ ürün çekildi.
- [x] **Eşleştirme Servisi (Normalizer):** Perakendeci verilerini Referans Kütüphanesi ile eşleştiren LLM tabanlı Entity Resolution servisi yazıldı.
- [x] **Web UI (Prototip):** Streamlit tabanlı canlı sepet destekli arayüz hazırlandı.

### 🟡 Sırada Bekleyenler / Hatalar
- [ ] **Eksik Veri (RTX 5000/Intel Ultra):** Mevcut 24k kütüphane eski kaldı. `tuckerandrew21/pc-part-dataset` fork'undan güncel verilerin çekilip "Transformer" scripti ile kütüphaneye yamanması gerekiyor.
- [ ] **Normalizer Kategori Kayması:** RAM (`memory`), Kasa (`case`) ve Soğutucu (`cooler`) kategorileri veritabanındaki `ram`, `pccase` ve `cpucooler` isimleriyle eşleşmediği için Normalizer bu parçaları henüz tam işleyemedi.
- [ ] **Iterative Upgrade Hatası:** `optimize_build` fonksiyonu bazen bütçeyi öncelikli parçalardan (RAM/Kasa) çalıp ekran kartına aktarıyor, bu da eksik parçalı sistemlere yol açıyor. Hard constraint eklenmeli.
- [ ] **FPS Tahmini:** Seçilen donanımın popüler oyunlardaki performansını hesaplayan tool.

---

## 📝 Lisans
MIT License
