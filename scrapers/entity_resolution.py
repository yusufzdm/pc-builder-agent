"""
scrapers/entity_resolution.py

Yeni perakendeci urunlerini (new_items_<cat>.json) referans kutuphanesindeki
(components koleksiyonu) urunlerle eslestirir.

Akis:
  1) Her yeni urun icin vector search ile en yakin K aday bul
  2) GPT-4o-mini'ye "ayni urun mu?" diye sor (marka + model + kilit spec'leri kontrol et)
  3) Sonucu 3 gruba ayir:
       matched: yuksek confidence (>=0.85), component_id ata
       review : orta confidence (0.55-0.85) veya marka uyumsuzlugu, manuel inceleme
       new    : hicbir adayla eslesmeyen, components'a eklenmeye aday
  4) Output: scrapers/data/er/<retailer>_<cat>_<status>.json

Modlar:
  python scrapers/entity_resolution.py --category cpu             (tek kategori)
  python scrapers/entity_resolution.py                            (tum kategoriler)
  python scrapers/entity_resolution.py --apply                    (eslesenleri DB'ye yaz)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_components_collection, get_inventory_collection
from database.laptop_filter import is_laptop_component
from database.accessory_filter import is_accessory as is_accessory_check
from database.er_validator import validate_er_match

load_dotenv()

# --- AYARLAR ---
DATA_ROOT = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "data" / "er"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Retailer -> data folder mapping
RETAILER_DIRS = {
    "vatan": DATA_ROOT / "vatan",
    "teknosa": DATA_ROOT / "teknosa",
    "mediamarkt": DATA_ROOT / "mediamarkt",
}

EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"
TOP_K_CANDIDATES = 5
MATCH_THRESHOLD = 0.75
REVIEW_THRESHOLD = 0.55

CATEGORIES = ["cpu", "motherboard", "gpu", "memory", "storage", "case", "psu", "cooler"]

# PC builder icin junk -> ne CPU ne kasa parcasi, aksesuar/sarf malzeme
JUNK_KEYWORDS = [
    "termal macun", "thermal paste", "termal pad", "thermal pad",
    "minus pad",
    "fan kontolcü", "fan kontrolcü", "fan controller",
    "macun temizley", "paste cleaner",
    "kablo uzatma", "anakart vida", "yedek pil",
    "upgrade kit", "upgrade kiti",
    "server fan", "proliant",
]


def is_junk(name: str) -> bool:
    """PC bilesenlerinden olmayan aksesuar/sarf urunu mu?"""
    n = (name or "").lower()
    return any(k in n for k in JUNK_KEYWORDS)


openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ============== EMBEDDING + VECTOR SEARCH ==============

def get_embedding(text: str) -> list[float]:
    resp = openai_client.embeddings.create(input=text, model=EMBEDDING_MODEL)
    return resp.data[0].embedding


def find_candidates(item: dict, k: int = TOP_K_CANDIDATES) -> list[dict]:
    """Vector search ile en yakin K adayi getirir."""
    name = item["name"]
    cat = item["component_type"]

    embedding = get_embedding(name)
    col = get_components_collection()

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": embedding,
                "numCandidates": 200,
                "limit": k,
                "filter": {"component_type": cat},
            }
        },
        {
            "$project": {
                "_id": 0,
                "embedding": 0,
                "description_text": 0,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]
    return list(col.aggregate(pipeline))


# ============== LLM MATCHING ==============

def summarize_candidate(c: dict) -> str:
    """LLM'e gonderilecek aday ozeti."""
    parts = [f"name: {c.get('name', '')}"]
    meta = c.get("metadata") or {}
    if meta.get("manufacturer"):
        parts.append(f"manufacturer: {meta['manufacturer']}")
    if meta.get("series"):
        parts.append(f"series: {meta['series']}")
    if c.get("socket"):
        parts.append(f"socket: {c['socket']}")
    if c.get("chipset"):
        parts.append(f"chipset: {c['chipset']}")
    if c.get("memory_type"):
        parts.append(f"memory_type: {c['memory_type']}")
    if c.get("capacity"):
        parts.append(f"capacity: {c['capacity']}")
    if c.get("wattage"):
        parts.append(f"wattage: {c['wattage']}")
    if c.get("memory") and isinstance(c.get("memory"), (int, float)):
        parts.append(f"vram: {c['memory']}GB")
    return " | ".join(parts)


def summarize_item(item: dict) -> str:
    """LLM'e gonderilecek perakendeci urun ozeti."""
    parts = [f"name: {item['name']}"]
    specs = item.get("raw_specs") or {}
    # Onemli spec'leri al
    for key in ["İşlemci Markası", "Soket Tipi", "Marka", "Tip", "Bellek Türü",
                "Kapasite", "RAM Tipi", "Form Faktör", "Watt", "VRAM",
                "Chipset", "Soket Türü"]:
        if key in specs and specs[key]:
            parts.append(f"{key}: {specs[key]}")
    return "\n".join(parts)


SYSTEM_PROMPT = """Sen bir e-ticaret urun esleme uzmanisin. Bir Turk perakendeci listing'iyle referans veritabanindaki adaylari karsilastiracaksin.

GORE: Aday listesinden hangisi (varsa) perakendeci urunuyle AYNI urun. Ayni model/seri/SKU olmasa bile, ayni urun ailesinin bir varyanti olabilir — bu da MATCH sayilir.

KURALLAR:
1) MARKA (manufacturer) MUTLAKA ESITLENMELI. Farkli markalar asla esleseyemez. Bu kural ozellikle yerel/no-name Turk markalari ile global markalar arasinda KESINDIR:
   YASAK ornekler:
   - Bory != Micron / Crucial / Samsung / Kingston
   - TwinMOS != Crucial / Samsung / Kingston / G.Skill
   - Hi-Level != Transcend / Samsung
   - Xaser / Xaser Winnfox != Gigabyte / MSI / Asus
   - Turbox != Asus / Gigabyte
   - Zeiron != VisionTek / Asus
   - Dragos != ASRock / Gigabyte / MSI
   - PowerBoost != Deepcool / ID-COOLING / Cooler Master
   - Izoly != ADATA / Crucial
   - OEM != bilinen herhangi bir marka
   - High Power != bilinen brand'ler (kendisi de bir marka, alias degil)
   Ayni markanin alt-marka/alias'lari kabul: "ASUS ROG" = "Asus", "MSI Gaming" = "MSI", "G.SKILL Trident" = "G.Skill", "ADATA XPG" = "ADATA", "Gigabyte AORUS" = "Gigabyte", "Cooler Master Hyper" = "Cooler Master", "Western Digital WD" = "WD".
2) MODEL/SERIES gevsek esleseyebilir. Kucuk varyantlar matchtir:
   - Renk farki (Black/White/RGB/non-RGB)
   - OC/non-OC, X/non-X varyant (Ryzen 5600 ~ 5600X kabul EDILMEZ — bunlar farkli SKU)
   - Kit varyasyonu (1x16 vs 2x8 ayni RAM model adi)
   - Box/Tray ayrim (BOX/TRAY ayni cipi - matchtir)
   - Tower air cooler boyut varyantlari (Hyper 212 LED ~ Hyper 212 RGB matchtir)
   - PSU efficiency rating ayni ama "Plus" yazimi farkli (80 Plus Gold ~ 80+ Gold)
3) TEMEL KIMLIK ESLESMELI:
   - CPU: ayni model numarasi (i5-13400F = i5-13400F, ama i5-13400 != i5-13400F)
   - RAM: kapasite + tip (DDR4/DDR5) + hiz
   - PSU: wattaj
   - Motherboard: chipset + soket
   - GPU: ayni cip (RTX 4070 = RTX 4070, ama 4070 != 4070 Super != 4070 Ti)
   - Storage: kapasite + arayuz (NVMe/SATA)
4) Aday score'u >= 0.70 ise ciddi degerlendir, varyant kabul edilebiliyorsa MATCH ver.
5) Emin degilsen confidence orta-dusuk ver (0.55-0.75), bu review'a gider.

CIKTI: Sadece JSON.
{
  "match_index": 0 | 1 | 2 | 3 | 4 | null,
  "confidence": 0.0-1.0,
  "brand_match": true | false,
  "reason": "Kisa Turkce aciklama (40-80 kelime)"
}
"""


def llm_match(item: dict, candidates: list[dict]) -> dict:
    """LLM'e match sorusu gonderir."""
    item_str = summarize_item(item)
    cand_str = "\n".join(
        f"[{i}] {summarize_candidate(c)} (score: {c.get('score', 0):.2f})"
        for i, c in enumerate(candidates)
    )
    user_msg = f"""Perakendeci urunu:
{item_str}

Adaylar:
{cand_str}

Hangi aday ayni urun? JSON cevap ver."""

    try:
        resp = openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        return {"match_index": None, "confidence": 0.0, "brand_match": False, "reason": f"LLM hatasi: {e}"}


# ============== ANA AKIS ==============

def classify_item(item: dict) -> dict:
    """Tek bir urunu siniflandirir, sonuc ekleyerek dondurur."""
    candidates = find_candidates(item)

    if not candidates:
        return {"status": "new", "reason": "vector search aday bulamadi"}

    # Top score cok dusukse direkt new
    if candidates[0]["score"] < 0.55:
        return {
            "status": "new",
            "reason": f"top score dusuk ({candidates[0]['score']:.2f})",
            "top_candidate": candidates[0].get("name"),
        }

    llm = llm_match(item, candidates)
    conf = llm.get("confidence", 0.0)
    idx = llm.get("match_index")
    brand_ok = llm.get("brand_match", False)

    if idx is not None and conf >= MATCH_THRESHOLD and brand_ok:
        chosen = candidates[idx]
        return {
            "status": "matched",
            "component_id": chosen.get("component_id"),
            "component_name": chosen.get("name"),
            "score": chosen.get("score"),
            "confidence": conf,
            "reason": llm.get("reason"),
        }
    elif idx is not None and conf >= REVIEW_THRESHOLD:
        chosen = candidates[idx]
        return {
            "status": "review",
            "candidate_component_id": chosen.get("component_id"),
            "candidate_name": chosen.get("name"),
            "score": chosen.get("score"),
            "confidence": conf,
            "brand_match": brand_ok,
            "reason": llm.get("reason"),
            "all_candidates": [c.get("name") for c in candidates],
        }
    else:
        return {
            "status": "new",
            "confidence": conf,
            "reason": llm.get("reason", "LLM aday onaylamadi"),
            "all_candidates": [c.get("name") for c in candidates],
        }


def process_category(category: str, retailer: str = "vatan") -> dict:
    """Bir kategorideki tum yeni urunleri isle."""
    src_dir = RETAILER_DIRS.get(retailer)
    if not src_dir:
        print(f"  ! Retailer {retailer} icin dizin yok"); return {}
    src = src_dir / f"new_items_{category}.json"
    if not src.exists():
        print(f"  ! {src.name} yok ({retailer})")
        return {}

    items = json.load(open(src, encoding="utf-8"))
    if not items:
        print(f"  ! {src.name} bos")
        return {}

    junk_items = [it for it in items if is_junk(it.get("name", ""))]
    items = [it for it in items if not is_junk(it.get("name", ""))]
    if junk_items:
        print(f"  > {len(junk_items)} junk urun pre-filter ile atlaniyor (LLM'e gitmeyecek)")
        junk_path = OUTPUT_DIR / f"{retailer}_{category}_junk.json"
        with open(junk_path, "w", encoding="utf-8") as f:
            json.dump(junk_items, f, ensure_ascii=False, indent=2)

    # Aksesuar/yanlış-kategori pre-filter: kasa fanı, montaj kiti, kasa standı vs.
    # Build için kullanılamaz, LLM çağrısı israf, DB'ye girmemeli.
    accessory_items = []
    valid_items = []
    for it in items:
        is_acc, reason = is_accessory_check(
            name=it.get("name"), retailer_title=it.get("name"),
            url=it.get("url"), component_type=category,
        )
        if is_acc:
            it["_accessory_reason"] = reason
            accessory_items.append(it)
        else:
            valid_items.append(it)
    items = valid_items
    if accessory_items:
        print(f"  > {len(accessory_items)} aksesuar/yanlis-kategori pre-filter ile atlaniyor")
        acc_path = OUTPUT_DIR / f"{retailer}_{category}_accessory.json"
        with open(acc_path, "w", encoding="utf-8") as f:
            json.dump(accessory_items, f, ensure_ascii=False, indent=2)

    # Laptop pre-filter: laptop bileşenleri DB için kullanılamaz, LLM çağrısı israf.
    laptop_items = []
    desktop_items = []
    for it in items:
        is_lap, reason = is_laptop_component(
            name=it.get("name"), retailer_title=it.get("name"),
            component_type=category,
        )
        if is_lap:
            it["_laptop_reason"] = reason
            laptop_items.append(it)
        else:
            desktop_items.append(it)
    items = desktop_items
    if laptop_items:
        print(f"  > {len(laptop_items)} laptop bileseni pre-filter ile atlaniyor (LLM'e gitmeyecek, DB'ye girmeyecek)")
        lap_path = OUTPUT_DIR / f"{retailer}_{category}_laptop.json"
        with open(lap_path, "w", encoding="utf-8") as f:
            json.dump(laptop_items, f, ensure_ascii=False, indent=2)

    print(f"\n=== {retailer.upper()} {category.upper()}: {len(items)} yeni urun isleniyor ===")
    matched, review, new = [], [], []

    for i, item in enumerate(items, 1):
        print(f"  [{i}/{len(items)}] {item['name'][:60]}...", end=" ", flush=True)
        try:
            result = classify_item(item)
        except Exception as e:
            print(f"HATA: {e}")
            result = {"status": "error", "error": str(e)}

        merged = {**item, "_er": result}
        status = result.get("status", "error")
        print(f"{status}")

        if status == "matched":
            matched.append(merged)
        elif status == "review":
            review.append(merged)
        elif status == "new":
            new.append(merged)

        # Rate limit
        if i % 20 == 0:
            time.sleep(1)

    # Yaz
    for status, lst in [("matched", matched), ("review", review), ("new", new)]:
        out = OUTPUT_DIR / f"{retailer}_{category}_{status}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(lst, f, ensure_ascii=False, indent=2)
        print(f"  ✓ {out.name}: {len(lst)}")

    return {"matched": len(matched), "review": len(review), "new": len(new)}


RETAILER_NAME_MAP = {
    "vatan": "Vatan Bilgisayar",
    "teknosa": "Teknosa",
    "mediamarkt": "MediaMarkt",
}


def apply_matched(retailer: str = "vatan"):
    """matched JSON'lari okuyup inventory'ye yazar.
    Junk + Aksesuar + Laptop bileşenleri + ER mismatch ATLANIR — DB'ye hiç girmezler.
    (Pre-filter zaten LLM aşamasında çoğunu eler, bu defensive katman.)"""
    inv = get_inventory_collection()
    comp = get_components_collection()
    total = 0
    skipped_junk = 0
    skipped_accessory = 0
    skipped_laptop = 0
    skipped_mismatch = 0
    retailer_label = RETAILER_NAME_MAP.get(retailer, retailer)
    for cat in CATEGORIES:
        p = OUTPUT_DIR / f"{retailer}_{cat}_matched.json"
        if not p.exists():
            continue
        items = json.load(open(p, encoding="utf-8"))
        added = 0
        for item in items:
            if is_junk(item.get("name", "")):
                skipped_junk += 1
                continue
            # Aksesuar/yanlış-kategori (kasa fanı, montaj kiti, kasa standı)
            is_acc, acc_reason = is_accessory_check(
                name=item.get("name"), retailer_title=item.get("name"),
                url=item.get("url"), component_type=item.get("component_type"),
            )
            if is_acc:
                skipped_accessory += 1
                print(f"    ⊘ aksesuar skip: {(item.get('name') or '')[:60]}  ({acc_reason})")
                continue
            # Laptop bileşeni
            is_lap, lap_reason = is_laptop_component(
                name=item.get("name"),
                retailer_title=item.get("name"),
                component_type=item.get("component_type"),
            )
            if is_lap:
                skipped_laptop += 1
                print(f"    ⊘ laptop skip: {(item.get('name') or '')[:60]}  ({lap_reason})")
                continue
            er = item["_er"]
            # ER mismatch kontrolü: components.name (referans) ile retailer_title/url
            # arasında DDR tipi/wattaj/PCIe gen tutarlı mı? Tutarsızsa link yanlış
            # ürüne gidiyor (RAM DDR4↔DDR5, PSU 400W↔350W gibi feedback bug'ları).
            comp_doc = comp.find_one({"component_id": er["component_id"]}, {"name": 1})
            comp_name = (comp_doc or {}).get("name")
            is_valid, mismatch_reason = validate_er_match(
                components_name=comp_name,
                retailer_title=item.get("name"),
                url=item.get("url"),
                component_type=item.get("component_type"),
            )
            if not is_valid:
                skipped_mismatch += 1
                print(f"    ⊘ ER mismatch skip: {(item.get('name') or '')[:60]}  ({mismatch_reason})")
                continue
            doc = {
                "component_id": er["component_id"],
                "component_type": item["component_type"],
                "retailer": item.get("retailer", retailer_label),
                "retailer_title": item["name"],
                "url": item["url"],
                "price": item["price"],
                "in_stock": item["in_stock"],
                "last_seen_at": item.get("scraped_at"),
                "_er_confidence": er.get("confidence"),
            }
            inv.update_one({"url": item["url"]}, {"$set": doc}, upsert=True)
            total += 1
            added += 1
        print(f"  ✓ {cat}: {added}/{len(items)} matched eklendi")
    print(f"\nToplam {total} urun inventory'ye eklendi. "
          f"Atlananlar: {skipped_junk} junk + {skipped_accessory} aksesuar + "
          f"{skipped_laptop} laptop + {skipped_mismatch} ER mismatch.")


def cleanup_existing_junk():
    """Mevcut inventory'de zaten kayitli junk urunleri sil."""
    inv = get_inventory_collection()
    docs = list(inv.find({}, {"_id": 0, "url": 1, "retailer_title": 1}))
    junk_urls = [d["url"] for d in docs if is_junk(d.get("retailer_title", ""))]
    if not junk_urls:
        print("  Mevcut inventory'de junk yok.")
        return
    print(f"  {len(junk_urls)} junk urun bulundu. Siliniyor...")
    for url in junk_urls[:5]:
        print(f"    - {url[:80]}")
    res = inv.delete_many({"url": {"$in": junk_urls}})
    print(f"  ✓ {res.deleted_count} kayit silindi")


def rerun_non_matched(retailer: str, category: str | None = None) -> dict:
    """Eskiden review/new olanlari yeni prompt+threshold ile yeniden isle.
    Mevcut matched'i koru, yeni matched bulunanlari ekle."""
    targets = [category] if category else CATEGORIES
    summary = {}

    for cat in targets:
        old_matched_path = OUTPUT_DIR / f"{retailer}_{cat}_matched.json"
        old_review_path = OUTPUT_DIR / f"{retailer}_{cat}_review.json"
        old_new_path = OUTPUT_DIR / f"{retailer}_{cat}_new.json"

        if not all(p.exists() for p in [old_matched_path, old_review_path, old_new_path]):
            print(f"  ! {cat}: eski ER dosyalari eksik, atlandi")
            continue

        old_matched = json.load(open(old_matched_path, encoding="utf-8"))
        old_review = json.load(open(old_review_path, encoding="utf-8"))
        old_new = json.load(open(old_new_path, encoding="utf-8"))

        # Junk pre-filter (yeni eklenmis pattern'ler eski tarama dahil olmustu)
        retry_pool = [
            it for it in (old_review + old_new)
            if not is_junk(it.get("name", ""))
        ]

        if not retry_pool:
            print(f"  {cat}: yeniden islenecek urun yok")
            summary[cat] = {"new_matched": 0, "still_review": 0, "still_new": 0}
            continue

        print(f"\n=== {retailer.upper()} {cat.upper()} RERUN: {len(retry_pool)} urun (yeni threshold={MATCH_THRESHOLD}) ===")

        new_matched = []
        new_review = []
        new_new = []

        for i, item in enumerate(retry_pool, 1):
            print(f"  [{i}/{len(retry_pool)}] {item['name'][:60]}...", end=" ", flush=True)
            try:
                # Eski _er meta'yi temizle, yeniden classify et
                clean_item = {k: v for k, v in item.items() if k != "_er"}
                result = classify_item(clean_item)
            except Exception as e:
                print(f"HATA: {e}")
                result = {"status": "error", "error": str(e)}

            merged = {**{k: v for k, v in item.items() if k != "_er"}, "_er": result}
            status = result.get("status", "error")
            print(status)

            if status == "matched":
                new_matched.append(merged)
            elif status == "review":
                new_review.append(merged)
            elif status == "new":
                new_new.append(merged)

            if i % 20 == 0:
                time.sleep(1)

        # Birlestirilmis matched: eski + yeni
        merged_matched = old_matched + new_matched
        with open(old_matched_path, "w", encoding="utf-8") as f:
            json.dump(merged_matched, f, ensure_ascii=False, indent=2)
        with open(old_review_path, "w", encoding="utf-8") as f:
            json.dump(new_review, f, ensure_ascii=False, indent=2)
        with open(old_new_path, "w", encoding="utf-8") as f:
            json.dump(new_new, f, ensure_ascii=False, indent=2)

        summary[cat] = {
            "new_matched": len(new_matched),
            "still_review": len(new_review),
            "still_new": len(new_new),
            "total_matched_now": len(merged_matched),
        }
        print(f"  ✓ {cat}: +{len(new_matched)} yeni matched (toplam: {len(merged_matched)}), "
              f"review: {len(new_review)}, new: {len(new_new)}")

    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retailer", default="vatan", choices=list(RETAILER_DIRS.keys()),
                        help="Hangi retailer icin ER (default: vatan)")
    parser.add_argument("--category", help="Sadece tek kategori")
    parser.add_argument("--apply", action="store_true", help="Matched'leri inventory'ye uygula")
    parser.add_argument("--cleanup-junk", action="store_true", help="Mevcut inventory'deki junk urunleri sil")
    parser.add_argument("--rerun-non-matched", action="store_true",
                        help="Sadece eskiden review/new olanlari yeni prompt+threshold ile tekrar isle")
    args = parser.parse_args()

    if args.cleanup_junk:
        print("=== JUNK CLEANUP ===")
        cleanup_existing_junk()
        return

    if args.apply:
        print(f"=== APPLY MODE ({args.retailer}) ===")
        cleanup_existing_junk()
        print()
        apply_matched(args.retailer)
        return

    if args.rerun_non_matched:
        print("=" * 60)
        print(f"RERUN NON-MATCHED ({args.retailer.upper()}) — threshold={MATCH_THRESHOLD}")
        print("=" * 60)
        summary = rerun_non_matched(args.retailer, args.category)
        print("\n" + "=" * 60)
        print("OZET (RERUN)")
        print("=" * 60)
        print(f"  {'kategori':<15} {'+matched':>10} {'review':>8} {'new':>8} {'toplam_matched':>16}")
        for cat, s in summary.items():
            if not s:
                continue
            print(f"  {cat:<15} {s.get('new_matched', 0):>10} {s.get('still_review', 0):>8} "
                  f"{s.get('still_new', 0):>8} {s.get('total_matched_now', 0):>16}")
        return

    print("=" * 60)
    print(f"ENTITY RESOLUTION ({args.retailer.upper()})")
    print("=" * 60)

    targets = [args.category] if args.category else CATEGORIES
    summary = {}
    for cat in targets:
        s = process_category(cat, retailer=args.retailer)
        summary[cat] = s

    print("\n" + "=" * 60)
    print("OZET")
    print("=" * 60)
    print(f"  {'kategori':<15} {'matched':>8} {'review':>8} {'new':>8}")
    for cat, s in summary.items():
        if not s:
            continue
        print(f"  {cat:<15} {s.get('matched', 0):>8} {s.get('review', 0):>8} {s.get('new', 0):>8}")
    print(f"\n  Sonraki adim: python scrapers/entity_resolution.py --retailer {args.retailer} --apply")


if __name__ == "__main__":
    main()
