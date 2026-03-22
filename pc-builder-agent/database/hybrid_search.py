"""
database/hybrid_search.py
MongoDB Vector Search ($vectorSearch) ile inventory $match (bütçe/stok) birleştiren
hibrit arama fonksiyonları.
"""

import os
import sys
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _get_query_embedding(query: str) -> list[float]:
    """Arama sorgusunu vektöre çevirir."""
    response = openai_client.embeddings.create(
        input=query,
        model=EMBEDDING_MODEL,
    )
    return response.data[0].embedding


def hybrid_search(
    query: str,
    component_type: str,
    max_price: Optional[int] = None,
    max_results: int = 5,
    ignore_stock: bool = False,
    filters: Optional[dict] = None,
) -> list[dict]:
    """
    Kategori bazında MongoDB Hybrid Search yapar.
    filters: {'socket': 'AM4', 'wattage': 650} gibi teknik kısıtlar.
    """
    query_embedding = _get_query_embedding(query)
    db = get_db()
    components_col = db["components"]

    # Ek filtreleri hazırla
    match_filter = {"component_type": component_type}
    if not ignore_stock:
        match_filter["is_in_stock"] = True
    if filters:
        for k, v in filters.items():
            if v: match_filter[k] = v

    if ignore_stock:
        # Araştırma Modu (Shopping yok)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": 500,
                    "limit": max_results * 5,
                    "filter": match_filter 
                }
            },
            {"$match": match_filter},
            {"$project": {"embedding": 0, "description_text": 0, "_id": 0, "score": {"$meta": "vectorSearchScore"}}},
            {"$limit": max_results}
        ]
        return list(components_col.aggregate(pipeline))

    # Shopping Pipeline (Join'li)
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_embedding,
                "numCandidates": 1000,
                "limit": max_results * 10,
                "filter": match_filter
            }
        },
        {"$match": match_filter},
        {"$project": {"embedding": 0, "description_text": 0, "_id": 0, "score": {"$meta": "vectorSearchScore"}}},
        {
            "$lookup": {
                "from": "inventory",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "inventory_info",
            }
        },
        {"$unwind": "$inventory_info"},
        {
            "$addFields": {
                "price": "$inventory_info.price",
                "in_stock": "$inventory_info.in_stock",
            }
        },
        {
            "$match": {
                "in_stock": True,
                **({"price": {"$lte": max_price}} if max_price is not None else {}),
            }
        },
        {"$project": {"inventory_info": 0}},
        {"$sort": {"score": -1}},
        {"$limit": max_results},
    ]

    try:
        results = list(components_col.aggregate(pipeline))
        return results
    except Exception as e:
        print(f"  ⚠️  Vector Search hatası: {e}")
        return []


def text_search(
    query: str,
    component_type: str,
    max_price: Optional[int] = None,
    max_results: int = 5,
    ignore_stock: bool = False,
    filters: Optional[dict] = None,
) -> list[dict]:
    """Fallback: Regex araması + Teknik filtreler."""
    db = get_db()
    
    # Filtreleri hazırla
    base_filter: dict = {"component_type": component_type}
    if not ignore_stock:
        base_filter["in_stock"] = True
    if max_price is not None:
        base_filter["price"] = {"$lte": max_price}
    if filters:
        for k, v in filters.items():
            if v: base_filter[k] = v

    if ignore_stock:
        col = db["components"]
        # Teknik özellikler için regex
        search_filter = {**base_filter, "name": {"$regex": query, "$options": "i"}}
        return list(col.find(search_filter, {"embedding": 0, "_id": 0}).limit(max_results))

    inventory_col = db["inventory"]
    regex_filter = {**base_filter, "name": {"$regex": query, "$options": "i"}}
    
    results = list(inventory_col.aggregate(_build_text_pipeline(regex_filter, max_results)))
    if not results:
        results = list(inventory_col.aggregate(_build_text_pipeline(base_filter, max_results)))
    return results


def _build_text_pipeline(match_filter: dict, max_results: int) -> list:
    return [
        {"$match": match_filter},
        {"$sort": {"price": -1}},
        {"$limit": max_results},
        {
            "$lookup": {
                "from": "components",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "tech_specs",
            }
        },
        {"$unwind": {"path": "$tech_specs", "preserveNullAndEmptyArrays": True}},
        {
            "$addFields": {
                "socket": "$tech_specs.socket",
                "tdp": "$tech_specs.tdp",
                "cores": "$tech_specs.cores",
                "vram": "$tech_specs.vram",
                "length": "$tech_specs.length",
                "wattage": "$tech_specs.wattage",
                "memory_type": "$tech_specs.memory_type",
                "type": "$tech_specs.type",
                "capacity": "$tech_specs.capacity",
                "has_igpu": "$tech_specs.has_igpu",
                "max_gpu_length": "$tech_specs.max_gpu_length",
            }
        },
        {"$project": {"_id": 0, "tech_specs": 0}},
    ]


def safe_search(
    query: str,
    component_type: str,
    max_price: Optional[int] = None,
    max_results: int = 5,
    ignore_stock: bool = False,
    filters: Optional[dict] = None,
) -> list[dict]:
    """Tüm aramalarda teknik filtre desteği."""
    try:
        results = hybrid_search(query, component_type, max_price, max_results, ignore_stock, filters)
        if results:
            return results
        return text_search(query, component_type, max_price, max_results, ignore_stock, filters)
    except Exception as e:
        return text_search(query, component_type, max_price, max_results, ignore_stock, filters)


if __name__ == "__main__":
    # Hızlı test
    print("🔍 Hybrid Search Testi...")
    results = safe_search("GeForce RTX 4070", "gpu")
    for r in results:
        print(f"  • {r.get('name')} — {r.get('price', 'STOKTA YOK')} TL")
