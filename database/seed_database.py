"""
database/seed_database.py
Mock JSON verilerini components ve inventory olarak MongoDB'ye yükler.
Var olan verilerin üzerine yazmaz (upsert kullanır - idempotent).
Embedding oluşturma: text-embedding-3-small (1536 dim).
"""

import os
import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Proje kök dizinini path'e ekle
sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_components_collection, get_inventory_collection
from database.laptop_filter import is_laptop_component
from database.accessory_filter import is_accessory as is_accessory_check

load_dotenv()

# Sabitleri
SAMPLE_DIR = Path(__file__).parent.parent / "sample_data"
CATEGORIES = ["cpu", "motherboard", "gpu", "memory", "case", "psu", "storage", "cooler"]
EMBEDDING_MODEL = "text-embedding-3-small"
BATCH_SIZE = 20  # API rate limit için

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def build_component_text(item: dict, category: str) -> str:
    """
    Bir bileşen için embedding'e gönderilecek zengin metin oluşturur.
    Bu metin ne kadar açıklayıcıysa, vektör araması o kadar iyi çalışır.
    """
    parts = [f"{category.upper()}: {item.get('name', '')}"]

    if category == "cpu":
        parts += [
            f"Soket: {item.get('socket', '')}",
            f"Çekirdek: {item.get('cores', '')}",
            f"TDP: {item.get('tdp', '')}W",
            f"Dahili GPU: {'var' if item.get('has_igpu') else 'yok'}",
        ]
    elif category == "motherboard":
        parts += [
            f"Soket: {item.get('socket', '')}",
            f"Form Faktör: {item.get('form_factor', '')}",
            f"RAM Tipi: {item.get('memory_type', '')}",
            f"RAM Slotu: {item.get('memory_slots', '')}",
        ]
    elif category == "gpu":
        parts += [
            f"VRAM: {item.get('vram', '')}GB",
            f"Uzunluk: {item.get('length', '')}mm",
            f"TDP: {item.get('tdp', '')}W",
        ]
    elif category == "memory":
        parts += [
            f"Tip: {item.get('type', '')}",
            f"Kapasite: {item.get('capacity', '')}GB",
            f"Hız: {item.get('speed', '')}MHz",
        ]
    elif category == "case":
        parts += [
            f"Form Faktör: {item.get('form_factor', '')}",
            f"Max GPU Uzunluk: {item.get('max_gpu_length', '')}mm",
            f"Max Soğutucu Yüksekliği: {item.get('max_cpu_cooler_height', '')}mm",
        ]
    elif category == "psu":
        parts += [
            f"Watt: {item.get('wattage', '')}W",
            f"Sertifika: {item.get('efficiency', '')}",
            f"Modüler: {'evet' if item.get('modular') else 'hayır'}",
        ]
    elif category == "storage":
        parts += [
            f"Kapasite: {item.get('capacity', '')}",
            f"Tip: {item.get('type', '')}",
            f"Arayüz: {item.get('interface', '')}",
        ]
    elif category == "cooler":
        parts += [
            f"RPM: {item.get('rpm', '')}",
            f"Ses Seviyesi: {item.get('noise_level', '')}dB",
            f"Renk: {item.get('color', '')}",
        ]

    return " | ".join(filter(None, parts))


def get_embedding(text: str) -> list[float]:
    """OpenAI API'den embedding alır."""
    response = openai_client.embeddings.create(
        input=text,
        model=EMBEDDING_MODEL,
    )
    return response.data[0].embedding


def seed_category(category: str) -> int:
    """
    Tek bir kategoriyi MongoDB'ye upsert eder.
    Returns: Eklenen/güncellenen kayıt sayısı
    """
    json_path = SAMPLE_DIR / f"{category}.json"
    if not json_path.exists():
        print(f"⚠️  {json_path} bulunamadı, atlanıyor.")
        return 0

    with open(json_path, encoding="utf-8") as f:
        items = json.load(f)

    components_col = get_components_collection()
    inventory_col = get_inventory_collection()

    count = 0
    # Kategori haritalama (Dosya adı -> DB Kategorisi)
    cat_map = {
        "storage": "internal-hard-drive",
        "cooler": "cpu-cooler",
        "cpu": "cpu",
        "motherboard": "motherboard",
        "gpu": "gpu",
        "memory": "memory",
        "case": "case",
        "psu": "psu"
    }
    db_category = cat_map.get(category, category)

    for i, item in enumerate(items):
        component_id = item.get("id") or item.get("name").lower().replace(" ", "-")
        price = item.pop("price", 0)  # Fiyatı ayır (inventory'ye gidecek)

        # ─── components koleksiyonu ───
        component_text = build_component_text(item, category)

        try:
            embedding = get_embedding(component_text)
        except Exception as e:
            print(f"  ❌ Embedding hatası ({item.get('name')}): {e}")
            embedding = []

        # Aksesuar / yanlış-kategori? Otomatik SKIP — DB'ye hiç girmez.
        is_acc, acc_reason = is_accessory_check(
            name=item.get("name"), component_type=category,
        )
        if is_acc:
            print(f"  ⊘ aksesuar skip: {item.get('name', '')[:60]}  ({acc_reason})")
            continue

        # Laptop bileşeni mi? Otomatik flag — search/optimize_build bunu filtreler.
        is_lap, lap_reason = is_laptop_component(
            name=item.get("name"),
            component_type=category,
            form_factor=(item.get("form_factor") or
                        (item.get("memory") or {}).get("form_factor") if isinstance(item.get("memory"), dict) else None),
        )

        component_doc = {
            **item,
            "category": db_category,
            "component_id": component_id,
            "description_text": component_text,
            "embedding": embedding,
        }
        if is_lap:
            component_doc["is_laptop"] = True
            component_doc["_laptop_reason"] = lap_reason

        components_col.update_one(
            {"component_id": component_id},
            {"$set": component_doc},
            upsert=True,
        )

        # ─── inventory koleksiyonu ───
        inventory_doc = {
            "component_id": component_id,
            "category": db_category,
            "name": item.get("name"),
            "price": price,
            "in_stock": True,
        }
        if is_lap:
            inventory_doc["is_laptop"] = True
        inventory_col.update_one(
            {"component_id": component_id},
            {"$set": inventory_doc},
            upsert=True,
        )

        count += 1

        # Batch delay — API rate limit
        if (i + 1) % BATCH_SIZE == 0:
            print(f"  ... {i + 1}/{len(items)} işlendi, 1s bekleniyor...")
            time.sleep(1)

    return count


def main():
    print("=" * 55)
    print("🌱 PC Builder Agent — Veritabanı Tohumlama (Seed)")
    print("=" * 55)
    print(f"📂 Veri kaynağı: {SAMPLE_DIR}\n")

    total = 0
    for category in CATEGORIES:
        print(f"📦 {category.upper()} işleniyor...")
        n = seed_category(category)
        print(f"   ✅ {n} kayıt upsert edildi.\n")
        total += n

    print("=" * 55)
    print(f"🎉 Seed tamamlandı! Toplam: {total} bileşen işlendi.")
    print("   • components koleksiyonu: teknik özellikler + embeddings")
    print("   • inventory koleksiyonu:  fiyatlar + stok bilgisi")
    print("=" * 55)

    # Atlas Vector Search index uyarısı
    from database.mongo_client import create_vector_search_index
    create_vector_search_index()


if __name__ == "__main__":
    main()
