"""
agents/tools.py
LangChain @tool dekoratörü ile tanımlı LLM araç seti.
"""

import json
import sys
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.hybrid_search import safe_search
from agents.logic_engine import PCBuilderLogic

logic = PCBuilderLogic()

# ─── Tool Şemaları (Pydantic) ───

class ComponentSearchInput(BaseModel):
    query: str = Field(description="Kullanıcının doğal dil araması. Örn: 'oyun için güçlü', 'sessiz soğutma'")
    max_price: Optional[int] = Field(None, description="Maksimum fiyat (TL). Bütçe filtresi.")
    socket: Optional[str] = Field(None, description="Soket tipi filtresi (örn: LGA1700, AM5, AM4)")
    wattage: Optional[int] = Field(None, description="Minimum PSU wattajı (örn: 650, 750)")
    memory_type: Optional[str] = Field(None, description="RAM tipi (örn: DDR4, DDR5)")

class SelectComponentInput(BaseModel):
    component_type: str = Field(description="Kategori: cpu, motherboard, gpu, memory, case, psu, storage, cooler")
    component_json: str = Field(description="Seçilen ürünün tüm JSON verisi (arama sonucundan gelen obje)")

class OptimizeBuildInput(BaseModel):
    budget: int = Field(description="Toplam bütçe (TL)")
    use_case: str = Field(description="Kullanım amacı: gaming, architecture, rendering, office, general")

class ReferenceSearchInput(BaseModel):
    query: str = Field(description="Aranacak ürünün tam adı veya modeli. Örn: 'i7-4770', 'GTX 1080'")
    component_type: str = Field(description="Kategori: cpu, motherboard, gpu, memory, case, psu, storage, cooler")

# ─── Yardımcı Fonksiyonlar ───

def _format_results(results: list[dict]) -> str:
    """Arama sonuçlarını okunabilir JSON string'e çevirir."""
    if not results:
        return "SONUÇ YOK — Bu kriterlere uygun stokta ürün bulunamadı. Başka bir kategori veya bütçe dene."
    clean = []
    for r in results:
        r.pop("embedding", None)
        r.pop("description_text", None)
        r.pop("_id", None)
        r.pop("score", None)
        clean.append(r)
    header = f"[VERİTABANI SONUÇLARI — SADECE AŞAĞIDAN ÖNER, BAŞKA ÜRÜN EKLEME]\n"
    return header + json.dumps(clean, ensure_ascii=False, indent=2)

# ─── Arama Araçları ───

@tool(args_schema=ComponentSearchInput)
def search_cpu(query: str, max_price: Optional[int] = None, socket: Optional[str] = None) -> str:
    """CPU (işlemci) araması yapar."""
    filters = {"socket": socket} if socket else None
    results = safe_search(query, logic.CATEGORY_MAP["cpu"], max_price, filters=filters)
    return _format_results(results)

@tool(args_schema=ComponentSearchInput)
def search_motherboard(query: str, max_price: Optional[int] = None, socket: Optional[str] = None, memory_type: Optional[str] = None) -> str:
    """Anakart araması yapar."""
    filters = {}
    if socket: filters["socket"] = socket
    if memory_type: filters["memory_type"] = memory_type
    results = safe_search(query, logic.CATEGORY_MAP["motherboard"], max_price, filters=filters)
    return _format_results(results)

@tool(args_schema=ComponentSearchInput)
def search_gpu(query: str, max_price: Optional[int] = None, **kwargs) -> str:
    """Ekran kartı araması yapar."""
    results = safe_search(query, logic.CATEGORY_MAP["gpu"], max_price)
    return _format_results(results)

@tool(args_schema=ComponentSearchInput)
def search_memory(query: str, max_price: Optional[int] = None, memory_type: Optional[str] = None, **kwargs) -> str:
    """RAM (bellek) araması yapar."""
    filters = {"memory_type": memory_type} if memory_type else None
    results = safe_search(query, logic.CATEGORY_MAP["memory"], max_price, filters=filters)
    return _format_results(results)

@tool(args_schema=ComponentSearchInput)
def search_case(query: str, max_price: Optional[int] = None, **kwargs) -> str:
    """Kasa araması yapar."""
    results = safe_search(query, logic.CATEGORY_MAP["case"], max_price)
    return _format_results(results)

@tool(args_schema=ComponentSearchInput)
def search_psu(query: str, max_price: Optional[int] = None, wattage: Optional[int] = None, **kwargs) -> str:
    """PSU araması yapar."""
    filters = {"wattage": {"$gte": wattage}} if wattage else None
    results = safe_search(query, logic.CATEGORY_MAP["psu"], max_price, filters=filters)
    return _format_results(results)

@tool(args_schema=ComponentSearchInput)
def search_storage(query: str, max_price: Optional[int] = None, **kwargs) -> str:
    """SSD/HDD araması yapar."""
    results = safe_search(query, logic.CATEGORY_MAP["storage"], max_price)
    return _format_results(results)

@tool(args_schema=ComponentSearchInput)
def search_cooler(query: str, max_price: Optional[int] = None, **kwargs) -> str:
    """Soğutucu araması yapar."""
    results = safe_search(query, logic.CATEGORY_MAP["cooler"], max_price)
    return _format_results(results)

@tool(args_schema=ReferenceSearchInput)
def search_reference_library(query: str, component_type: str) -> str:
    """
    TÜM REFERANS KÜTÜPHANESİNDE (24.000+ parça) teknik araştırma yapar.
    Sadece kullanıcının elinde olan eski parçalar veya teknik bilgi almak için kullanılır.
    Stokta olup olmadığına bakmaz, fiyat döndürmez.
    """
    results = safe_search(query, logic.CATEGORY_MAP.get(component_type, component_type), ignore_stock=True)
    return _format_results(results)

# ─── Mantıksal Araçlar ───

@tool
def calculate_psu(cpu_tdp: int, gpu_tdp: int) -> str:
    """Gerekli PSU wattajını hesaplar."""
    min_watt = logic.calculate_min_psu(cpu_tdp, gpu_tdp)
    return json.dumps({"minimum_psu_watt": min_watt}, ensure_ascii=False)

@tool
def check_compatibility(selected_json: str) -> str:
    """Uyumluluk kontrolü yapar."""
    try:
        parts = json.loads(selected_json)
        result = logic.check_compatibility(parts)
        if result["valid"] and not result["warnings"]:
            return "✅ TEKNİK ONAY: Tüm bileşenler uyumlu."
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"❌ Hata: {str(e)}"

@tool(args_schema=SelectComponentInput)
def select_component(component_type: str, component_json: str) -> str:
    """Bileşeni sisteme kaydeder (Doğrulama ile)."""
    try:
        comp = json.loads(component_json)
        comp_id = comp.get("component_id")
        from database.mongo_client import get_db
        db = get_db()
        actual = db["inventory"].find_one({"component_id": comp_id})
        if not actual: return "❌ Hata: Ürün veritabanında bulunamadı."
        return f"✅ {component_type.upper()} seçildi: {comp.get('name')}"
    except Exception as e:
        return f"❌ Hata: {str(e)}"

@tool(args_schema=OptimizeBuildInput)
def optimize_build(budget: int, use_case: str = "general") -> str:
    """Otomatik sistem toplar."""
    result = logic.optimize_build(budget, use_case)
    return json.dumps(result, ensure_ascii=False, indent=2)

@tool
def check_budget(selected_json: str, target_budget: int) -> str:
    """Bütçe kontrolü yapar."""
    try:
        parts = json.loads(selected_json)
        total = sum(p.get("price", 0) for p in parts.values() if isinstance(p, dict))
        return f"Toplam: {total:,} TL / Hedef: {target_budget:,} TL"
    except Exception as e:
        return f"❌ Hata: {str(e)}"

@tool
def generate_final_report(selected_json: str) -> str:
    """Markdown tablo formatında özet rapor sunar."""
    try:
        parts = json.loads(selected_json)
        table = "| Kategori | Ürün | Fiyat |\n| :--- | :--- | :--- |\n"
        total = 0
        for cat, comp in parts.items():
            if isinstance(comp, dict):
                price = comp.get("price", 0)
                table += f"| {cat.upper()} | {comp.get('name')} | {price:,} TL |\n"
                total += price
        table += f"| **TOPLAM** | | **{total:,} TL** |"
        return table
    except Exception as e:
        return f"❌ Rapor hatası: {str(e)}"

@tool
def calculate_budget_allocation(budget: int, use_case: str = "general") -> str:
    """Bütçe dağılımını hesaplar."""
    profile = logic.ALLOCATION_PROFILES.get(use_case.lower(), logic.ALLOCATION_PROFILES["general"])
    allocations = {cat: f"{int(budget * pct):,} TL" for cat, pct in profile.items()}
    return json.dumps(allocations, ensure_ascii=False, indent=2)

ALL_TOOLS = [
    search_cpu, search_motherboard, search_gpu, search_memory, search_case, search_psu,
    search_storage, search_cooler, search_reference_library, calculate_psu, check_compatibility,
    select_component, optimize_build, check_budget, generate_final_report,
    calculate_budget_allocation
]
