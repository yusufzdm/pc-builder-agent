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
pip install langchain langchain-openai langgraph pymongo openai python-dotenv
```

### Ortam Değişkenleri (.env)
```env
OPENAI_API_KEY=sk-...
MONGO_URI=mongodb+srv://...
MONGO_DB_NAME=buildcores_db
```

### Çalıştırma
```bash
cd pc-builder-agent
python main.py
```

---

## 📁 Proje Klasör Yapısı

- `pc-builder-agent/`
  - `agents/`: Ajan mantığı, LangGraph grafı ve araçlar (`tools.py`, `logic_engine.py`, `graph_builder.py`).
  - `database/`: MongoDB bağlantısı ve hibrit arama algoritmaları.
  - `main.py`: Uygulama giriş noktası.
- `README.md`: Bu master döküman.

---

## 🛠️ Mevcut Durum ve Yol Haritası (Roadmap)

### 🟢 Tamamlananlar
- [x] **MongoDB & Vector Search:** 24k dökümanlı kütüphane ve Atlas Vector Search entegrasyonu.
- [x] **Kategori Standardizasyonu:** Tüm sistem `component_type` alanına geçirildi.
- [x] **Gelişmiş Filtreleme:** Soket, RAM tipi ve Watt bazlı teknik aramalar aktif.
- [x] **Legacy Desteği:** Kullanıcının elindeki eski parçaları tanıma yeteneği (`search_reference_library`).
- [x] **LangGraph Stabilizasyonu:** Sonsuz döngü ve boş yanıt hataları giderildi.
- [x] **Perakendeci Scraper:** Vatan Bilgisayar'dan dinamik ürün kazıma sistemi (Hybrid Scroller) yazıldı ve 1.200+ ürün çekildi.
- [x] **Eşleştirme Servisi (Normalizer):** Perakendeci verilerini Referans Kütüphanesi ile eşleştiren LLM tabanlı Entity Resolution servisi yazıldı (479 adet kusursuz eşleşme sisteme dahil edildi).
- [x] **Satın Alma Linkleri:** Ajanın topladığı sistemlerdeki parçalara doğrudan satın alma bağlantıları (URL) eklendi.

### 🟡 Sırada Bekleyenler
- [ ] **FPS Tahmini:** Seçilen donanımın popüler oyunlardaki performansını hesaplayan tool.
- [ ] **Web UI:** Streamlit veya React tabanlı bir kullanıcı arayüzü entegrasyonu.
- [ ] **Çoklu Perakendeci:** İtopya, Sinerji gibi diğer satıcıların sisteme dahil edilmesi.

---

## 📝 Lisans
MIT License
