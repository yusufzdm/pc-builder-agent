"""
database/mongo_client.py
MongoDB Atlas bağlantı kurulumu ve koleksiyon/index yönetimi.
"""

import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

load_dotenv()

_client = None


def get_client() -> MongoClient:
    """Singleton MongoDB client döndürür."""
    global _client
    if _client is None:
        uri = os.getenv("MONGO_URI")
        if not uri:
            raise ValueError("MONGO_URI ortam değişkeni bulunamadı!")
        _client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
        # Bağlantıyı test et
        _client.admin.command("ping")
        print("✅ MongoDB Atlas bağlantısı kuruldu.")
    return _client


def get_db():
    """buildcores_db veritabanı objesini döndürür."""
    db_name = os.getenv("MONGO_DB_NAME", "buildcores_db")
    return get_client()[db_name]


def get_components_collection():
    """components koleksiyonunu döndürür."""
    return get_db()["components"]


def get_inventory_collection():
    """inventory koleksiyonunu döndürür."""
    return get_db()["inventory"]


def create_vector_search_index():
    """
    Atlas Vector Search index oluşturur.
    M0 (ücretsiz) katmanda Atlas UI veya API üzerinden oluşturulması gerekir.
    Bu fonksiyon, index'in var olup olmadığını kontrol eder ve yoksa kullanıcıyı bilgilendirir.
    
    Index JSON (Atlas UI'da Search > Create Index sekmesine yapıştır):
    {
      "fields": [
        {
          "type": "vector",
          "path": "embedding",
          "numDimensions": 1536,
          "similarity": "cosine"
        },
        {
          "type": "filter",
          "path": "category"
        }
      ]
    }
    """
    try:
        col = get_components_collection()
        indexes = list(col.list_search_indexes())
        index_names = [idx.get("name") for idx in indexes]

        if "vector_index" in index_names:
            print("✅ 'vector_index' zaten mevcut.")
        else:
            print(
                "⚠️  'vector_index' bulunamadı!\n"
                "Atlas UI'da şu adımları izle:\n"
                "  1. cluster0 > Browse Collections > buildcores_db\n"
                "  2. Search Indexes > Create Search Index\n"
                "  3. 'JSON Editor' seç, index adı: 'vector_index'\n"
                "  4. Aşağıdaki JSON'u yapıştır:\n"
                "{\n"
                '  "fields": [\n'
                '    {"type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine"},\n'
                '    {"type": "filter", "path": "category"}\n'
                "  ]\n"
                "}"
            )
    except OperationFailure as e:
        print(f"⚠️  Index kontrolü başarısız (M0 limitasyonu olabilir): {e}")
    except Exception as e:
        print(f"⚠️  Index kontrolü sırasında hata: {e}")


if __name__ == "__main__":
    try:
        db = get_db()
        print(f"📦 Veritabanı: {db.name}")
        print(f"📋 Koleksiyonlar: {db.list_collection_names()}")
        create_vector_search_index()
    except ServerSelectionTimeoutError:
        print("❌ MongoDB'ye bağlanılamadı. MONGO_URI'yi kontrol et.")
