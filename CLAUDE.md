# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Proje Özeti

Türkçe doğal dil destekli, Nöro-Sembolik mimariye sahip PC toplama asistanı. LLM (GPT-4o-mini) kullanıcı niyetini anlar, deterministik Logic Engine (CSP) donanım uyumluluğunu garanti eder. 24.000+ bileşen referans kütüphanesi MongoDB Atlas Vector Search üzerinde çalışır.

## Çalıştırma

```bash
# Ajan (terminal chatbot)
python main.py

# Senaryo testleri (5 farklı kullanıcı senaryosu, gerçek graf akışı)
python test_user_scenarios.py

# Veritabanı tohumlama (sample_data/ JSON'larını MongoDB'ye yükler + embedding oluşturur)
python database/seed_database.py

# Vatan Bilgisayar scraper (undetected-chromedriver gerektirir)
python scrapers/vatan_scraper.py
```

## Ortam Değişkenleri (.env)

- `OPENAI_API_KEY` — GPT-4o-mini ve text-embedding-3-small için
- `MONGO_URI` — MongoDB Atlas connection string
- `MONGO_DB_NAME` — Varsayılan: `buildcores_db`

## Mimari

### LangGraph Graf Akışı (DCG — Directed Cyclic Graph)

```
START → chatbot → [tools_condition] → tools (BudgetAwareToolNode) → validator → chatbot → ...
                 → END (tool çağrısı yoksa)
```

- **chatbot** (`graph_builder.py`): Sistem promptu ekler, `llm_with_tools.invoke()` çağırır. Son mesaj ToolMessage ise LLM'e "sonuçları sun" hatırlatması enjekte eder.
- **BudgetAwareToolNode** (`graph_builder.py`): Tool çağrılarını çalıştırır. `search_*` araçlarında `max_price` boşsa state'ten bütçe enjekte eder. `select_component` ve `optimize_build` sonuçlarını state'e yazar.
- **ValidatorNode** (`logic_engine.py`): Seçilen bileşenlere deterministik uyumluluk kontrolü uygular (soket, RAM tipi, form factor, GPU boyutu, PSU wattı, soğutucu yüksekliği). Bütçe aşımı kontrolü yapar (%10 tolerans). Kalan bütçe varsa proaktif upgrade önerisi üretir.

### AgentState (`graph_builder.py:AgentState`)

`messages`, `target_budget`, `current_spend`, `selected_components`, `errors`, `retry_count`, `use_case` alanlarını taşır. `messages` alanı `add_messages` reducer kullanır.

### Veri Mimarisi (Decoupled)

İki MongoDB koleksiyonu `component_id` üzerinden JOIN edilir:
- **`components`**: 24.262 döküman. Teknik özellikler + `embedding` (1536-dim, text-embedding-3-small). Atlas Vector Search index: `vector_index`.
- **`inventory`**: Perakendeci fiyat, stok, URL bilgisi. Şu an sadece Vatan Bilgisayar verisi aktif.

### Arama Katmanı (`database/hybrid_search.py`)

`safe_search()` → `hybrid_search()` (vector search + inventory lookup) → fallback: `text_search()` (regex). Vector search pipeline: `$vectorSearch` → `$match` (post-filter) → `$lookup` (inventory JOIN) → `$unwind` → fiyat/stok filtre → sıralama.

Pre-filter alanları (index'te tanımlı): `component_type`, `is_in_stock`. Post-filter: `socket`, `wattage`, `memory_type` gibi teknik filtreler `$match` aşamasında uygulanır.

### Tool Sistemi (`agents/tools.py`)

Kategori başına `search_*` araçları (cpu, motherboard, gpu, memory, case, psu, storage, cooler) + `search_reference_library` (stok dışı referans araması). Mantıksal araçlar: `optimize_build`, `check_compatibility`, `calculate_psu`, `select_component`, `check_budget`, `generate_final_report`, `calculate_budget_allocation`. Tümü `ALL_TOOLS` listesinde toplanır ve LLM'e bind edilir.

### Logic Engine (`agents/logic_engine.py:PCBuilderLogic`)

- `CATEGORY_MAP`: Kod adı → MongoDB `component_type` eşlemesi
- `ALLOCATION_PROFILES`: Kullanım senaryosuna göre bütçe dağılım yüzdeleri (gaming, architecture, rendering, office, general)
- `optimize_build()`: Sıralama: GPU → CPU → Motherboard (soket filtreli) → RAM (DDR filtreli) → storage/cooler/case → PSU (TDP hesaplı) → iteratif upgrade → bütçe aşımı downgrade
- `check_compatibility()`: 8 kontrol (soket, RAM tipi, RAM slot, form factor, GPU boyutu, soğutucu yüksekliği, PSU wattı, soğutucu gereksinimi)

## Bilinen Hatalar (TODO.md)

- `memory_type` filtresi çalışmıyor: DB'de alan nested (`memory.ram_type`), tool'lar düz `memory_type` gönderiyor
- Validator her tool response'unda `get_best_part_for_budget` çağırıyor → ekstra API call + MongoDB query (performans/maliyet sorunu)
- `optimize_build` bazen RAM/Kasa bütçesini başka kategoriye aktararak eksik parçalı sistem topluyor

## Dil

Tüm kullanıcı-facing metinler, prompt'lar ve yanıtlar Türkçe. Kod içi değişken/fonksiyon isimleri İngilizce.
