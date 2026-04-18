"""
agents/logic_engine.py
Mevcut PCBuilderLogic sınıfı korunmaktadır.
Yeni: ValidatorNode — LangGraph state'ini değerlendiren deterministik düğüm.
"""

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Proje kök dizinini path'e ekle
sys.path.insert(0, str(Path(__file__).parent.parent))


class PCBuilderLogic:
    """
    Deterministik PC konfigürasyon mantık motoru.
    Uyumluluk kontrolü, bütçe hesaplama ve sistem optimizasyonu.
    """

    # Merkezi Kategori Eşleme (Kod Adı -> MongoDB component_type Adı)
    CATEGORY_MAP = {
        "cpu": "cpu",
        "motherboard": "motherboard",
        "gpu": "gpu",
        "memory": "memory",
        "case": "case",
        "psu": "psu",
        "storage": "storage",
        "cooler": "cooler"
    }

    # Turkiye fiyatlarina gore ayarlanmis butce dagilimlari
    ALLOCATION_PROFILES = {
        "gaming": {
            "gpu": 0.35, "cpu": 0.20, "motherboard": 0.10,
            "memory": 0.10, "storage": 0.10, "case": 0.04, "psu": 0.07, "cooler": 0.04
        },
        "architecture": {
            "gpu": 0.28, "cpu": 0.22, "motherboard": 0.11,
            "memory": 0.14, "storage": 0.10, "case": 0.06, "psu": 0.06, "cooler": 0.03
        },
        "rendering": {
            "gpu": 0.32, "cpu": 0.20, "motherboard": 0.11,
            "memory": 0.14, "storage": 0.10, "case": 0.05, "psu": 0.05, "cooler": 0.03
        },
        "office": {
            "gpu": 0.05, "cpu": 0.25, "motherboard": 0.18,
            "memory": 0.15, "storage": 0.15, "case": 0.10, "psu": 0.08, "cooler": 0.04
        },
        "general": {
            "gpu": 0.28, "cpu": 0.20, "motherboard": 0.12,
            "memory": 0.11, "storage": 0.10, "case": 0.07, "psu": 0.08, "cooler": 0.04
        },
    }

    def __init__(self):
        """
        Faz 1: Artık local JSON'dan değil, MongoDB'den veri çekiliyor.
        Bu sınıf sadece deterministik hesaplama yapıyor;
        veri çekme işi tools.py + hybrid_search.py'ye devredildi.
        """
        pass

    # ─── Birleşik Envanter Sorgusu ───

    def _query_inventory(self, component_type, max_price=None, filters=None, cheapest=False):
        """
        Birleşik inventory + components join sorgusu.
        cheapest=True → en ucuz, cheapest=False → bütçe dahilinde en pahalı (en iyi).
        filters: {"socket": "AM5", "memory.ram_type": "DDR4"} — nested field'lar desteklenir.
        """
        from database.mongo_client import get_db
        db = get_db()

        db_type = self.CATEGORY_MAP.get(component_type, component_type)

        inv_match = {"component_type": db_type, "in_stock": True}
        if max_price is not None:
            inv_match["price"] = {"$lte": max_price}

        comp_match = {}
        if filters:
            for k, v in filters.items():
                if v is not None:
                    comp_match[f"tech.{k}"] = v

        sort_stage = {"price": 1} if cheapest else {"price": -1}

        pipeline = [
            {"$match": inv_match},
            {"$lookup": {
                "from": "components",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "tech"
            }},
            {"$unwind": {"path": "$tech", "preserveNullAndEmptyArrays": True}},
        ]

        if comp_match:
            pipeline.append({"$match": comp_match})

        pipeline.extend([
            {"$sort": sort_stage},
            {"$limit": 1},
            {"$addFields": {
                "name": {"$ifNull": ["$tech.name", "$retailer_title"]},
                "socket": "$tech.socket",
                "tdp": "$tech.tdp",
                "specifications": "$tech.specifications",
                "memory": "$tech.memory",
                "form_factor": "$tech.form_factor",
                "ram_type": "$tech.ram_type",
                "capacity": "$tech.capacity",
                "speed": "$tech.speed",
                "modules": "$tech.modules",
                "wattage": "$tech.wattage",
                "length": "$tech.length",
                "max_video_card_length": "$tech.max_video_card_length",
                "max_cpu_cooler_height": "$tech.max_cpu_cooler_height",
                "supported_motherboard_form_factors": "$tech.supported_motherboard_form_factors",
                "cores": "$tech.cores",
                "vram": "$tech.vram",
                "has_igpu": "$tech.has_igpu",
                "type": "$tech.type",
                "height": "$tech.height",
            }},
            {"$project": {"tech": 0, "_id": 0}},
        ])

        results = list(db["inventory"].aggregate(pipeline))
        return results[0] if results else None

    def get_best_part_for_budget(self, component_type, max_price, filters=None):
        """Bütçe dahilinde en pahalı (= genelde en iyi) ürünü getirir. ValidatorNode uyumluluğu için wrapper."""
        return self._query_inventory(component_type, max_price, filters)

    # ─── Özel Seçim Metotları (PSU, Kasa) ───

    def _select_psu(self, max_price: int, min_wattage: int) -> dict | None:
        """Minimum watt'a uyan, bütçe dahilinde en pahalı PSU'yu getirir."""
        from database.mongo_client import get_db
        db = get_db()

        pipeline = [
            {"$match": {"component_type": "psu", "in_stock": True, "price": {"$lte": max_price}}},
            {"$lookup": {
                "from": "components",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "tech"
            }},
            {"$unwind": {"path": "$tech", "preserveNullAndEmptyArrays": True}},
            {"$match": {"tech.wattage": {"$gte": min_wattage}}},
            {"$sort": {"price": -1}},
            {"$limit": 1},
            {"$addFields": {
                "name": {"$ifNull": ["$tech.name", "$retailer_title"]},
                "wattage": "$tech.wattage",
                "type": "$tech.type",
                "form_factor": "$tech.form_factor",
            }},
            {"$project": {"tech": 0, "_id": 0}},
        ]

        results = list(db["inventory"].aggregate(pipeline))
        return results[0] if results else None

    def _select_compatible_case(self, max_price: int, mobo_form_factor: str = "") -> dict | None:
        """Anakart form factor'ına uyumlu, bütçe dahilinde en pahalı kasayı getirir."""
        from database.mongo_client import get_db
        db = get_db()

        pipeline = [
            {"$match": {"component_type": "case", "in_stock": True, "price": {"$lte": max_price}}},
            {"$lookup": {
                "from": "components",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "tech"
            }},
            {"$unwind": {"path": "$tech", "preserveNullAndEmptyArrays": True}},
            {"$sort": {"price": -1}},
        ]

        results = list(db["inventory"].aggregate(pipeline))

        # Form factor uyumlu olanları filtrele
        if mobo_form_factor:
            compatible = []
            for r in results:
                tech = r.get("tech", {}) or {}
                supported = tech.get("supported_motherboard_form_factors", [])
                if not supported or mobo_form_factor in supported:
                    compatible.append(r)
            if compatible:
                results = compatible

        if not results:
            return None

        best = results[0]
        tech = best.pop("tech", {}) or {}
        best.pop("_id", None)
        best["name"] = tech.get("name") or best.get("retailer_title", "?")
        best["supported_motherboard_form_factors"] = tech.get("supported_motherboard_form_factors", [])
        best["max_video_card_length"] = tech.get("max_video_card_length")
        best["max_cpu_cooler_height"] = tech.get("max_cpu_cooler_height")
        best["form_factor"] = tech.get("form_factor", "")
        return best

    @staticmethod
    def _name_of(part: dict) -> str:
        """Parça ismini normalize eder."""
        return part.get("name") or part.get("retailer_title") or part.get("metadata", {}).get("name") or "?"

    # ─── RAM Yardımcıları ───

    def _ram_pipeline(self, ddr_type: str, max_price: int = None, sort_by: str = "capacity",
                      min_capacity: int = None) -> list:
        """
        RAM aggregation pipeline: inventory + components join.
        components.ram_type ve components.capacity field'larını kullanır.
        sort_by: "capacity" (en yüksek kapasite) veya "price_asc" (en ucuz).
        min_capacity: Minimum GB filtresi (örn. 16 → en az 16GB).
        """
        match_stage = {"component_type": "memory", "in_stock": True}
        if max_price is not None:
            match_stage["price"] = {"$lte": max_price}

        sort_stage = {"capacity": -1, "price": -1} if sort_by == "capacity" else {"price": 1}

        tech_match = {"tech.ram_type": ddr_type}
        if min_capacity:
            tech_match["tech.capacity"] = {"$gte": min_capacity}

        return [
            {"$match": match_stage},
            {"$lookup": {
                "from": "components",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "tech"
            }},
            {"$unwind": "$tech"},
            {"$match": tech_match},
            {"$addFields": {
                "name": {"$ifNull": ["$tech.name", "$retailer_title"]},
                "ram_type": "$tech.ram_type",
                "capacity": "$tech.capacity",
                "speed": "$tech.speed",
                "cas_latency": "$tech.cas_latency",
                "modules": "$tech.modules",
                "form_factor": "$tech.form_factor",
                "component_id": "$tech.component_id",
            }},
            {"$sort": sort_stage},
            {"$limit": 1},
            {"$project": {"tech": 0, "_id": 0}},
        ]

    def _get_cheapest_ram_by_ddr(self, ddr_type: str) -> dict | None:
        """DDR tipine göre en ucuz stokta RAM'i getirir."""
        from database.mongo_client import get_db
        results = list(get_db()["inventory"].aggregate(self._ram_pipeline(ddr_type, sort_by="price_asc")))
        return results[0] if results else None

    def _select_best_ram(self, ddr_type: str, max_price: int) -> dict | None:
        """Bütçe dahilinde en yüksek kapasiteli RAM'i getirir."""
        from database.mongo_client import get_db
        results = list(get_db()["inventory"].aggregate(self._ram_pipeline(ddr_type, max_price, sort_by="capacity")))
        return results[0] if results else None

    # ─── Platform Keşfi ve Seçimi ───

    def _discover_platforms(self) -> list[dict]:
        """
        Envanterdeki tüm geçerli (socket, ddr_type) platform kombinasyonlarını keşfeder.
        Her platform için minimum maliyet (CPU + MB + RAM tabanı) hesaplar.
        Sadece 3 DB query kullanır (MB grupları + CPU tabanları + RAM tabanları).
        """
        from database.mongo_client import get_db
        db = get_db()

        # Query 1: Anakartlardan distinct (socket, ram_type) çiftleri + min fiyat
        mb_groups = list(db["inventory"].aggregate([
            {"$match": {"component_type": "motherboard", "in_stock": True}},
            {"$lookup": {
                "from": "components",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "tech"
            }},
            {"$unwind": "$tech"},
            {"$match": {"tech.socket": {"$ne": None}, "tech.memory.ram_type": {"$ne": None}}},
            {"$group": {
                "_id": {"socket": "$tech.socket", "ddr_type": "$tech.memory.ram_type"},
                "min_mb_price": {"$min": "$price"}
            }}
        ]))

        # Query 2: Her soket için en ucuz CPU fiyatı
        cpu_floors = {
            doc["_id"]: doc["min_price"]
            for doc in db["inventory"].aggregate([
                {"$match": {"component_type": "cpu", "in_stock": True}},
                {"$lookup": {
                    "from": "components",
                    "localField": "component_id",
                    "foreignField": "component_id",
                    "as": "tech"
                }},
                {"$unwind": "$tech"},
                {"$group": {"_id": "$tech.socket", "min_price": {"$min": "$price"}}}
            ])
        }

        # Query 3: Her DDR tipi için en ucuz RAM fiyatı
        ram_floors = {
            doc["_id"]: doc["min_price"]
            for doc in db["inventory"].aggregate([
                {"$match": {"component_type": "memory", "in_stock": True}},
                {"$lookup": {
                    "from": "components",
                    "localField": "component_id",
                    "foreignField": "component_id",
                    "as": "tech"
                }},
                {"$unwind": "$tech"},
                {"$group": {"_id": "$tech.ram_type", "min_price": {"$min": "$price"}}}
            ])
        }

        # Platformları birleştir
        platforms = []
        for doc in mb_groups:
            socket = doc["_id"]["socket"]
            ddr_type = doc["_id"]["ddr_type"]

            cpu_price = cpu_floors.get(socket)
            ram_price = ram_floors.get(ddr_type)
            if cpu_price is None or ram_price is None:
                continue

            platforms.append({
                "socket": socket,
                "ddr_type": ddr_type,
                "platform_floor": doc["min_mb_price"] + cpu_price + ram_price,
            })

        return platforms

    def _select_platform(self, budget: int, use_case: str) -> dict | None:
        """
        Bütçeye ve kullanım amacına en uygun platformu otomatik seçer.
        Platform = (socket, ddr_type). Geri kalan her şey bu kısıtlarla otomatik uyumlu.

        Skorlama: headroom (bütçe - platform floor) + DDR5 bonus (bütçenin %5'i).
        other_floor hesaplanmaz — tüm platformlar için aynı olduğundan sıralamayı değiştirmez.
        """
        platforms = self._discover_platforms()
        if not platforms:
            return None

        for p in platforms:
            p["headroom"] = budget - p["platform_floor"]
            ddr5_bonus = int(budget * 0.05) if p["ddr_type"] == "DDR5" else 0
            p["score"] = p["headroom"] + ddr5_bonus

        viable = [p for p in platforms if p["headroom"] >= 0]
        if viable:
            return max(viable, key=lambda p: p["score"])
        else:
            return min(platforms, key=lambda p: p["platform_floor"])

    # ─── Ana Optimizasyon ───

    def optimize_build(self, budget: int, use_case: str = "general", custom_allocations: dict = None) -> dict:
        """
        Platform-aware Floor + Weighted Remainder algoritması:
        0. Platform keşfi: (socket, ddr_type) bütçeye göre otomatik seçilir
        1. Her kategori için minimum fiyatı (taban) DB'den çek
        2. Bütçe < toplam taban → build impossible
        3. Artanı (bütçe - taban) use-case profiline göre dağıt
        4. Greedy upgrade: öncelik sırasıyla her parçayı yükselt
        5. Rebalance: harcanamayan payı sonraki kategoriye aktar
        """
        profile = custom_allocations or self.ALLOCATION_PROFILES.get(use_case.lower(), self.ALLOCATION_PROFILES["general"])
        all_categories = list(profile.keys())

        def total_spend(b):
            return sum(p.get("price", 0) for p in b.values() if isinstance(p, dict))

        # ══════════════════════════════════════════
        # FAZ 0: Platform Seçimi (otomatik, bütçeye göre)
        # ══════════════════════════════════════════

        platform = self._select_platform(budget, use_case)
        if not platform:
            return {"selected_components": {}, "total_spend": 0, "remaining_budget": budget,
                    "use_case": use_case, "error": "Stokta uyumlu platform bulunamadı."}

        selected_socket = platform["socket"]
        target_ddr = platform["ddr_type"]

        # ══════════════════════════════════════════
        # FAZ 1: Taban (Floor) — her kategorinin en ucuz parçası
        # ══════════════════════════════════════════

        floors = {}
        for cat in all_categories:
            if cat == "cpu":
                floors[cat] = self._query_inventory("cpu",
                    filters={"socket": selected_socket}, cheapest=True)
            elif cat == "motherboard":
                floors[cat] = self._query_inventory("motherboard",
                    filters={"socket": selected_socket, "memory.ram_type": target_ddr},
                    cheapest=True)
            elif cat == "memory":
                floors[cat] = self._get_cheapest_ram_by_ddr(target_ddr)
            else:
                floors[cat] = self._query_inventory(cat, cheapest=True)

        # Bulunamayan kategorileri çıkar
        floors = {k: v for k, v in floors.items() if v}
        floor_total = total_spend(floors)

        # Bütçe taban toplamının altındaysa uyarı ver
        if budget < floor_total:
            for cat, part in floors.items():
                part["name"] = self._name_of(part)
            return {
                "selected_components": floors,
                "total_spend": floor_total,
                "remaining_budget": budget - floor_total,
                "use_case": use_case,
                "platform": f"{selected_socket} / {target_ddr}",
                "warning": f"Minimum sistem maliyeti {floor_total:,} TL. Bütçeniz ({budget:,} TL) yetersiz, en ucuz parçalarla oluşturuldu."
            }

        # ══════════════════════════════════════════
        # FAZ 2: Artanı Dağıt (Weighted Remainder)
        # ══════════════════════════════════════════

        distributable = budget - floor_total
        ceilings = {}
        for cat in all_categories:
            floor_price = floors.get(cat, {}).get("price", 0)
            weight = profile.get(cat, 0)
            ceilings[cat] = floor_price + int(distributable * weight)

        # ══════════════════════════════════════════
        # FAZ 3: Greedy Upgrade — öncelik sırasıyla yükselt
        # ══════════════════════════════════════════

        # Öncelik sırası (use_case'e göre)
        if use_case.lower() == "gaming":
            priority = ["gpu", "cpu", "memory", "storage", "motherboard", "psu", "cooler", "case"]
        elif use_case.lower() == "office":
            priority = ["cpu", "memory", "storage", "motherboard", "gpu", "psu", "case", "cooler"]
        else:
            priority = ["gpu", "cpu", "memory", "storage", "motherboard", "psu", "cooler", "case"]

        build = dict(floors)  # Tabanla başla
        unspent = 0  # Bir kategoride harcanamayan pay

        for cat in priority:
            ceiling = ceilings.get(cat, 0) + unspent
            floor_part = floors.get(cat)
            if not floor_part:
                continue

            # --- RAM: DDR tipi + bütçe içinde en yüksek kapasite ---
            if cat == "memory":
                best_ram = self._select_best_ram(target_ddr, int(ceiling))
                if not best_ram:
                    best_ram = self._get_cheapest_ram_by_ddr(target_ddr)
                if best_ram:
                    build["memory"] = best_ram
                    unspent = max(0, ceiling - best_ram.get("price", 0))
                else:
                    unspent += ceiling - floor_part.get("price", 0)
                continue

            # --- Kasa: form factor uyumlu ---
            if cat == "case":
                mobo_ff = build.get("motherboard", {}).get("form_factor", "")
                best_case = self._select_compatible_case(int(ceiling), mobo_ff)
                if best_case:
                    build["case"] = best_case
                    unspent = max(0, ceiling - best_case.get("price", 0))
                else:
                    unspent += ceiling - floor_part.get("price", 0)
                continue

            # --- CPU: platform socket kısıtlı, anakartı da güncelle ---
            if cat == "cpu":
                better = self._query_inventory("cpu", int(ceiling),
                    filters={"socket": selected_socket})
                if better and better.get("price", 0) > floor_part.get("price", 0):
                    build["cpu"] = better
                    unspent = max(0, ceiling - better.get("price", 0))
                    # Anakartı da platform kısıtlarıyla güncelle
                    mobo_ceiling = ceilings.get("motherboard", 0) + max(unspent, 0)
                    mobo_better = self._query_inventory("motherboard", int(mobo_ceiling),
                        filters={"socket": selected_socket, "memory.ram_type": target_ddr})
                    if mobo_better:
                        build["motherboard"] = mobo_better
                else:
                    unspent += ceiling - floor_part.get("price", 0)
                continue

            # --- Anakart: CPU bloğunda yönetiliyor, tekrar yükseltme RAM uyumunu bozar ---
            if cat == "motherboard":
                mb_price = build.get("motherboard", {}).get("price", 0)
                unspent += max(0, ceiling - mb_price)
                continue

            # --- Genel upgrade: tavan bütçesiyle en iyi parçayı bul ---
            better = self._query_inventory(cat, int(ceiling))
            if better and better.get("price", 0) > floor_part.get("price", 0):
                build[cat] = better
                unspent = max(0, ceiling - better.get("price", 0))
            else:
                unspent += ceiling - floor_part.get("price", 0)

        # ══════════════════════════════════════════
        # FAZ 4: PSU — TDP hesabına göre
        # ══════════════════════════════════════════

        cpu_obj = build.get("cpu", {})
        gpu_obj = build.get("gpu", {})
        cpu_tdp = int(cpu_obj.get("specifications", {}).get("tdp") or cpu_obj.get("tdp", 65))
        gpu_tdp = int(gpu_obj.get("tdp", 200))
        min_psu_watt = self.calculate_min_psu(cpu_tdp, gpu_tdp)

        psu_ceiling = ceilings.get("psu", 0) + max(unspent, 0)
        psu = self._select_psu(int(psu_ceiling), min_psu_watt)
        if not psu:
            # Bütçe sınırı olmadan minimum watt'a uyan en ucuzu
            psu = self._select_psu(999999, min_psu_watt)
        if psu:
            build["psu"] = psu

        # ══════════════════════════════════════════
        # FAZ 5: Son kontroller
        # ══════════════════════════════════════════

        # İsim normalizasyonu
        for cat, part in build.items():
            part["name"] = self._name_of(part)

        spent = total_spend(build)
        warnings = []

        # Use-case bazlı minimum RAM kontrolü + otomatik rebalance
        min_ram_gb = {"gaming": 16, "architecture": 16, "rendering": 32, "office": 8, "general": 8}
        ram_cap = build.get("memory", {}).get("capacity", 0) or 0
        req = min_ram_gb.get(use_case.lower(), 8)
        if ram_cap < req:
            # Minimum kapasiteyi karşılayan en ucuz RAM'i bul
            from database.mongo_client import get_db
            adequate_ram_results = list(get_db()["inventory"].aggregate(
                self._ram_pipeline(target_ddr, sort_by="price_asc", min_capacity=req)
            ))
            adequate_ram = adequate_ram_results[0] if adequate_ram_results else None

            rebalanced = False
            if adequate_ram:
                extra_cost = adequate_ram["price"] - build.get("memory", {}).get("price", 0)
                if extra_cost > 0:
                    # GPU'yu 1 kademe düşürüp RAM'e bütçe aktar
                    gpu = build.get("gpu", {})
                    if gpu:
                        cheaper_gpu = self._query_inventory("gpu", int(gpu["price"] - extra_cost))
                        if cheaper_gpu and cheaper_gpu.get("price", 0) < gpu.get("price", 0):
                            saved = gpu["price"] - cheaper_gpu["price"]
                            if saved >= extra_cost:
                                build["gpu"] = cheaper_gpu
                                build["memory"] = adequate_ram
                                build["gpu"]["name"] = self._name_of(build["gpu"])
                                build["memory"]["name"] = self._name_of(build["memory"])
                                rebalanced = True
                                spent = total_spend(build)
                elif extra_cost <= 0:
                    # Zaten bütçe yetiyor, sadece RAM'i yükselt
                    build["memory"] = adequate_ram
                    build["memory"]["name"] = self._name_of(build["memory"])
                    rebalanced = True
                    spent = total_spend(build)

            if not rebalanced:
                ram_cap_final = build.get("memory", {}).get("capacity", 0) or 0
                if ram_cap_final < req:
                    warnings.append(
                        f"'{use_case}' kullanımı için minimum {req}GB RAM önerilir, "
                        f"mevcut seçim {ram_cap_final}GB. GPU düşürülerek de karşılanamadı."
                    )

        result = {
            "selected_components": build,
            "total_spend": spent,
            "remaining_budget": budget - spent,
            "use_case": use_case,
            "platform": f"{selected_socket} / {target_ddr}",
        }
        if warnings:
            result["warnings"] = warnings
        return result

    # ─── Deterministik Hesaplama Fonksiyonları ───

    def calculate_min_psu(self, cpu_tdp: int, gpu_tdp: int) -> int:
        """
        CPU ve GPU TDP'sine göre minimum gerekli PSU wattajını hesaplar.
        Formül: (CPU_TDP + GPU_TDP) * 1.5 + 100W (sistem overhead)
        En yakın 50W'a yuvarlar.
        """
        base_power = cpu_tdp + gpu_tdp
        recommended = int(base_power * 1.5) + 100
        return ((recommended + 49) // 50) * 50

    def check_compatibility(self, selected_components: dict) -> dict:
        """
        Seçilen bileşen sözlüğünü uyumluluk açısından kontrol eder.
        Fiziksel boyut (form factor), radyatör desteği ve teknik uyum.
        """
        errors = []
        warnings = []
        parts = selected_components

        cpu = parts.get("cpu", {})
        mobo = parts.get("motherboard", {})
        ram = parts.get("memory", {})
        gpu = parts.get("gpu", {})
        case = parts.get("case", {})
        psu = parts.get("psu", {})
        cooler = parts.get("cooler", {})
        storage = parts.get("storage", {})

        # ─── KONTROL 0: Eksik Parça Uyarıları ───
        if not storage:
            warnings.append("⚠️ DEPOLAMA EKSİK: Sistemde SSD veya HDD seçilmemiş. Windows/OS kurulamaz.")

        # ─── KONTROL 1: CPU ↔ Anakart Soket ───
        if cpu and mobo:
            cpu_socket = cpu.get("socket")
            mobo_socket = mobo.get("socket")
            if cpu_socket and mobo_socket and cpu_socket != mobo_socket:
                errors.append(
                    f"⛔ SOKET UYUMSUZLUĞU: İşlemci {cpu_socket} soket kullanıyor, "
                    f"Anakart ise {mobo_socket} soket. Birlikte çalışamazlar."
                )

        # ─── KONTROL 2: Anakart ↔ RAM Tipi ───
        if mobo and ram:
            mobo_mem = mobo.get("memory", {}).get("ram_type") if isinstance(mobo.get("memory"), dict) else mobo.get("memory_type")
            # Önce DB field'ından al, yoksa isimden parse et
            ram_type = ram.get("ram_type")
            if not ram_type:
                ram_meta = ram.get("metadata", {})
                ram_name = ram_meta.get("name", "") or ram.get("name", "")
                if "DDR5" in ram_name.upper():
                    ram_type = "DDR5"
                elif "DDR4" in ram_name.upper():
                    ram_type = "DDR4"
                elif "DDR3" in ram_name.upper():
                    ram_type = "DDR3"
            if mobo_mem and ram_type and mobo_mem != ram_type:
                errors.append(
                    f"⛔ RAM UYUMSUZLUĞU: Anakart {mobo_mem} destekliyor, "
                    f"seçilen RAM {ram_type} tipinde."
                )

            # --- RAM Kapasite ve Slot Kontrolü ---
            mobo_memory = mobo.get("memory", {}) if isinstance(mobo.get("memory"), dict) else {}
            max_mem = mobo_memory.get("max", 128)
            mobo_slots = int(mobo_memory.get("slots", 4))
            # RAM isminden (örn: 2x16GB) kaç modül olduğunu bulmaya çalış
            ram_name = ram.get("name", "").lower()
            stick_count = 1
            if "2x" in ram_name: stick_count = 2
            elif "4x" in ram_name: stick_count = 4

            if stick_count > mobo_slots:
                errors.append(f"⛔ RAM SLOT HATASI: Anakartta {mobo_slots} slot var, seçilen RAM kiti {stick_count} modül içeriyor.")

        # ─── KONTROL 3: Kasa ↔ Anakart (Form Factor) ───
        if case and mobo:
            # BuildCores: case.supported_motherboard_form_factors listesi var
            supported_ffs = case.get("supported_motherboard_form_factors", [])
            mobo_ff = (mobo.get("form_factor") or "").strip()

            if supported_ffs and mobo_ff:
                # Normalize et (buyuk/kucuk harf farki)
                supported_lower = [ff.lower() for ff in supported_ffs]
                if mobo_ff.lower() not in supported_lower:
                    errors.append(
                        f"⛔ FİZİKSEL UYUMSUZLUK: Seçilen anakart ({mobo_ff}) "
                        f"seçilen kasanın desteklediği form faktörler ({', '.join(supported_ffs)}) arasında değil."
                    )

        # ─── KONTROL 4: Kasa ↔ GPU Boyutu ───
        if case and gpu:
            max_gpu_len = case.get("max_video_card_length") or 999
            gpu_len = gpu.get("length") or 0
            try:
                max_gpu_len = int(max_gpu_len)
                gpu_len = int(gpu_len)
                if gpu_len > max_gpu_len:
                    errors.append(
                        f"⛔ FİZİKSEL HATA: Ekran kartı {gpu_len}mm uzunluğunda, "
                        f"kasa maksimum {max_gpu_len}mm GPU destekliyor."
                    )
            except (TypeError, ValueError):
                pass

        # ─── KONTROL 5: Kasa ↔ CPU Soğutucu Yüksekliği ───
        if case and cooler:
            max_cooler_h = case.get("max_cpu_cooler_height")
            cooler_h = cooler.get("height")
            if max_cooler_h and cooler_h:
                try:
                    if int(cooler_h) > int(max_cooler_h):
                        errors.append(
                            f"⛔ SOĞUTUCU SIĞMIYOR: Soğutucu {cooler_h}mm yüksekliğinde, "
                            f"kasa maksimum {max_cooler_h}mm destekliyor."
                        )
                except (TypeError, ValueError):
                    pass

        # ─── KONTROL 6: PSU Güç Yeterliliği ───
        if psu:
            cpu_tdp = cpu.get("specifications", {}).get("tdp") or cpu.get("tdp", 65)
            gpu_tdp = gpu.get("tdp", 200)
            try:
                required_watt = self.calculate_min_psu(int(cpu_tdp), int(gpu_tdp))
                psu_watt = psu.get("wattage") or psu.get("tech_specs", {}).get("wattage", 0)
                psu_watt = int(psu_watt)
                if psu_watt < required_watt:
                    warnings.append(
                        f"⚠️ GÜÇ UYARISI: PSU {psu_watt}W, sistem en az {required_watt}W istiyor. "
                        f"Daha yüksek wattlı PSU önerilir."
                    )
            except (TypeError, ValueError):
                pass

        # ─── KONTROL 7: Soğutucu Gereksinimi (High-End CPU) ───
        if cpu and not cooler:
            cpu_tdp = int(cpu.get("specifications", {}).get("tdp") or cpu.get("tdp", 65))
            cpu_name = cpu.get("name", "").lower()
            no_stock_cooler_keywords = ["k", "x", "kf", "ks", "x3d"]
            if cpu_tdp > 100 or any(kw in cpu_name.split() for kw in no_stock_cooler_keywords):
                warnings.append(f"⚠️ SOĞUTUCU UYARISI: Seçilen CPU ({cpu.get('name')}) kutusundan soğutucu çıkmaz veya çok ısınır. Harici bir CPU Cooler eklemelisiniz.")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# ─── ValidatorNode — LangGraph Düğümü ───

class ValidatorNode:
    """
    LangGraph graph_builder.py içinde kullanılacak 'validator' düğümü.
    AgentState'i alır, uyumluluk + bütçe kontrolü yapar, state'i günceller.
    """

    def __init__(self):
        self.logic = PCBuilderLogic()

    def __call__(self, state: dict) -> dict:
        """
        LangGraph node arayüzü. state alır, güncellenmiş state döndürür.
        """
        selected = state.get("selected_components", {})
        target_budget = state.get("target_budget", 0)
        use_case = state.get("use_case", "general")

        # ─── Uyumluluk Kontrolü ───
        if selected:
            compat = self.logic.check_compatibility(selected)
            new_errors = compat["errors"]
            new_warnings = compat["warnings"]
        else:
            new_errors = []
            new_warnings = []

        # ─── Harcama Hesaplama ───
        current_spend = sum(
            comp.get("price", 0)
            for comp in selected.values()
            if isinstance(comp, dict)
        )

        # ─── Bütçe Aşımı Kontrolü ───
        if target_budget > 0 and current_spend > target_budget * 1.10:
            new_errors.append(
                f"⛔ BÜTÇE AŞIMI: Mevcut sistem {current_spend:,} TL, "
                f"hedef bütçe {target_budget:,} TL (%10 tolerans aşıldı)."
            )

        # ─── Proaktif Yükseltme Önerileri (DETERMİNİSTİK) ───
        # Eğer bütçenin %5'inden fazla yer kaldıysa daha iyi bir parça öner
        remaining = target_budget - current_spend
        if remaining > target_budget * 0.03: # %3'ten fazla yer varsa
            for cat in ["gpu", "cpu", "storage"]: # En kritik 3 kategori
                current_part = selected.get(cat)
                if not current_part: continue

                max_price = current_part.get("price", 0) + remaining
                better = self.logic.get_best_part_for_budget(cat, int(max_price))

                if better and better.get("price", 0) > current_part.get("price", 0):
                    new_warnings.append(
                        f"✨ FIRSAT: {cat.upper()} kategorisinde {better.get('name')} modeline "
                        f"geçebilirsiniz. Bütçeniz buna yetiyor ve çok daha yüksek performans alırsınız."
                    )
                    break # Sadece bir tane en iyi fırsatı göster ki LLM kafası karışmasın

        return {
            "errors": new_errors + new_warnings,
            "current_spend": current_spend,
        }


if __name__ == "__main__":
    # Hızlı test
    validator = ValidatorNode()
    test_state = {
        "selected_components": {
            "cpu": {"socket": "AM5", "tdp": 65, "price": 8500},
            "motherboard": {"socket": "LGA1700", "memory_type": "DDR5", "price": 5000},
            "memory": {"type": "DDR5", "price": 3000},
        },
        "target_budget": 30000,
        "current_spend": 0,
        "errors": [],
    }
    result = validator(test_state)
    print("Validator Sonucu:")
    print(f"  Hatalar: {result['errors']}")
    print(f"  Harcama: {result['current_spend']:,} TL")
