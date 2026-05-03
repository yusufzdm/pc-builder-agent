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


# GPU yoğun use_case'ler — LP filter, GPU boost ve minimum-payment garantisi bunlarda aktif.
# `gpu_boost_params` dict'inin key'leriyle senkron tutulmalı.
GPU_HEAVY_USE_CASES = {"gaming", "rendering", "architecture", "design"}

# Düşük-tier chipsets — VRM zayıf, M.2 slotları Gen3 ile sınırlı, XMP/EXPO eksik.
# GPU-yoğun use_case'lerde sustained workload'da throttle riski (örn 14400F + H610
# → 30 dk render'da CPU thermal throttle). Office/general'de tolere edilir
# (bütçeye sığması için), gaming/rendering/architecture/design'da exclude edilir.
LOW_TIER_CHIPSETS = {
    "Intel H610", "Intel H510", "Intel H410", "Intel H310", "Intel H110",
    "Intel B360", "Intel H270", "Intel H170",
    "AMD A520", "AMD A320", "AMD A300", "AMD A620",
}


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
        # design: 2D/3D görsel tasarım (Photoshop, Illustrator, Figma, hafif video).
        # GPU orta-yüksek (8GB VRAM yeterli), RAM yüksek (32GB hedef), NVMe storage
        # öncelik (asset/scratch). Gaming kadar GPU-ağır değil ama office'ten çok
        # daha güçlü. Architecture'a benzer ama RAM ve storage'a biraz daha yer.
        "design": {
            "gpu": 0.28, "cpu": 0.20, "motherboard": 0.10,
            "memory": 0.16, "storage": 0.12, "case": 0.04, "psu": 0.07, "cooler": 0.03
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

    # Low Profile GPU regex — mid/full tower kasalarda gereksiz (yarım yükseklik kart,
    # düşük TDP, dar bellek bandı). Sadece SFF/OEM bilgisayarlar için tasarlanmış.
    LP_GPU_REGEX = r"\bLP\b|low.?profile|half.?height"

    # Chipset → maksimum resmi RAM hızı (MHz). Üretici spec'i + JEDEC.
    # XMP/EXPO destekleyen chipset'lerde gerçek max OC ile daha yüksek olabilir, ama
    # H610/H510 gibi düşük tier'lar XMP'siz kalır → DDR5-6000 modül burada JEDEC 4800'de
    # çalışır, kullanıcı boşa fazla para öder. Bu cap "resmi olarak garantili" hızdır.
    # Bilinmeyen chipset için DDR tipine göre conservative default uygulanır.
    CHIPSET_MAX_RAM_SPEED = {
        # Intel DDR5
        "intel h610": 4800, "intel b660": 4800, "intel h670": 4800, "intel z690": 4800,
        "intel h770": 5600, "intel b760": 5600, "intel z790": 5600,
        "intel b860": 6400, "intel z890": 6400,
        # Intel DDR4 (eski platformlar)
        "intel h510": 3200, "intel b560": 3200, "intel h570": 3200, "intel z590": 3200,
        "intel h410": 2933, "intel b460": 2933, "intel h470": 2933, "intel z490": 2933,
        "intel z390": 2666, "intel z370": 2666, "intel z270": 2666, "intel b360": 2666,
        "intel z170": 2400, "intel z97": 1866, "intel z68": 1600,
        # AMD DDR5 (AM5)
        "amd a620": 5200, "amd b650": 6400, "amd b650e": 6400,
        "amd x670": 6400, "amd x670e": 6400,
        "amd b850": 8000, "amd x870": 8000, "amd x870e": 8000,
        # AMD DDR4 (AM4)
        "amd a520": 3200, "amd b450": 3200, "amd x470": 3200,
        "amd b550": 4800, "amd x570": 4800,
        # AMD DDR3 (eski)
        "amd 970": 1866, "amd 990fx": 1866,
    }
    # DDR tipi bazlı conservative fallback (chipset bulunamazsa)
    DDR_DEFAULT_MAX_SPEED = {"DDR3": 1600, "DDR4": 3200, "DDR5": 4800}

    @classmethod
    def chipset_max_ram_speed(cls, chipset: str | None, ddr_type: str | None) -> int:
        """Chipset adından max RAM hızını bul; yoksa DDR tipine göre conservative."""
        if chipset:
            key = chipset.strip().lower()
            if key in cls.CHIPSET_MAX_RAM_SPEED:
                return cls.CHIPSET_MAX_RAM_SPEED[key]
        return cls.DDR_DEFAULT_MAX_SPEED.get((ddr_type or "").upper(), 4800)

    def _query_inventory(self, component_type, max_price=None, filters=None, cheapest=False,
                         raw_match=None, exclude_low_profile=False):
        """
        Birleşik inventory + components join sorgusu.
        cheapest=True → en ucuz, cheapest=False → bütçe dahilinde en pahalı (en iyi).
        filters: {"socket": "AM5", "memory.ram_type": "DDR4"} — nested field'lar desteklenir.
        raw_match: $match stage'ine direkt eklenecek dict (regex/operator destekli).
        exclude_low_profile: GPU sorgularında Low Profile kartları hariç tut.
        """
        from database.mongo_client import get_db
        db = get_db()

        db_type = self.CATEGORY_MAP.get(component_type, component_type)

        inv_match = {"component_type": db_type, "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}}
        if max_price is not None:
            inv_match["price"] = {"$lte": max_price}
        if exclude_low_profile:
            inv_match["retailer_title"] = {"$not": {"$regex": self.LP_GPU_REGEX, "$options": "i"}}

        comp_match = {}
        if filters:
            for k, v in filters.items():
                if v is not None:
                    comp_match[f"tech.{k}"] = v
        if raw_match:
            comp_match.update(raw_match)

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
                # Storage uyumlulugu icin gerekli
                "m2_slots": "$tech.m2_slots",
                "storage_devices": "$tech.storage_devices",
                "interface": "$tech.interface",
                # Motherboard chipset (RAM hız capi için)
                "chipset": "$tech.chipset",
                # Cooler socket compat (CPU socket eşleşme kontrolü için)
                "cpu_sockets": "$tech.cpu_sockets",
                "water_cooled": "$tech.water_cooled",
                "radiator_size": "$tech.radiator_size",
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
        """min_wattage <= PSU watt <= min_wattage*1.4 araliginda, butce dahilinde en uygun PSU.
        Oversize'i (2x asim) onlemek icin watt aralik kısıtli secim."""
        from database.mongo_client import get_db
        db = get_db()

        # Watt usT sınırı: min_wattage'in 1.4 kati (oversize tolerans)
        max_wattage = int(min_wattage * 1.4)

        pipeline = [
            {"$match": {"component_type": "psu", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}, "price": {"$lte": max_price}}},
            {"$lookup": {
                "from": "components",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "tech"
            }},
            {"$unwind": {"path": "$tech", "preserveNullAndEmptyArrays": True}},
            {"$match": {"tech.wattage": {"$gte": min_wattage, "$lte": max_wattage}}},
            # En uygun: aralik icinde en yuksek wattajlı (verim için) ama price'a göre orta seviye
            {"$sort": {"tech.wattage": -1, "price": -1}},
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
        if results:
            return results[0]

        # Aralikta hicbir uyumlu PSU yok — sadece min_wattage uyumu ile fallback
        fallback_pipeline = [
            {"$match": {"component_type": "psu", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}, "price": {"$lte": max_price}}},
            {"$lookup": {
                "from": "components",
                "localField": "component_id",
                "foreignField": "component_id",
                "as": "tech"
            }},
            {"$unwind": {"path": "$tech", "preserveNullAndEmptyArrays": True}},
            {"$match": {"tech.wattage": {"$gte": min_wattage}}},
            {"$sort": {"tech.wattage": 1, "price": 1}},  # min watt'a en yakın, en ucuz
            {"$limit": 1},
            {"$addFields": {
                "name": {"$ifNull": ["$tech.name", "$retailer_title"]},
                "wattage": "$tech.wattage",
                "type": "$tech.type",
                "form_factor": "$tech.form_factor",
            }},
            {"$project": {"tech": 0, "_id": 0}},
        ]
        results = list(db["inventory"].aggregate(fallback_pipeline))
        return results[0] if results else None

    def _select_compatible_case(self, max_price: int, mobo_form_factor: str = "") -> dict | None:
        """Anakart form factor'ına uyumlu, bütçe dahilinde en pahalı kasayı getirir."""
        from database.mongo_client import get_db
        db = get_db()

        pipeline = [
            {"$match": {"component_type": "case", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}, "price": {"$lte": max_price}}},
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

    @staticmethod
    def _cpu_has_igpu_from_name(name: str) -> bool | None:
        """CPU adindan iGPU var mi tespit. DB'de has_igpu field bos oldugu icin
        isim suffix'leri kullanilir.
        Intel: F veya KF suffix = iGPU yok, diger = iGPU var (default 12-14gen)
        AMD: G/GT suffix = iGPU var, diger = iGPU yok"""
        import re
        if not name:
            return None
        n = name.lower()
        # AMD CPUs
        if any(k in n for k in ["amd", "ryzen"]):
            return bool(re.search(r"\d{3,4}g[t]?\b", n))
        # Intel CPUs: 14400F, 14600KF, 13900KF — K opsiyonel, F sonunda
        if any(k in n for k in ["intel", "core "]):
            if re.search(r"\d{3,5}k?f\b", n):
                return False
            return True
        return None

    @staticmethod
    def _igpu_name_filter(socket: str) -> dict:
        """Socket'a gore iGPU'lu CPU'yu yakalayan name regex filter.
        $match stage'inde 'tech.metadata.name' uzerinde calistirilir."""
        s = (socket or "").lower()
        if "lga" in s or "1700" in s or "1851" in s or "1200" in s:
            # Intel: name'de F (veya KF) suffix YOK = iGPU var
            return {"tech.metadata.name": {"$not": {"$regex": r"\d{3,5}K?F\b"}}}
        # AMD/diger: G veya GT suffix VAR = iGPU var
        return {"tech.metadata.name": {"$regex": r"\d{3,4}G[T]?\b"}}

    # ─── RAM Yardımcıları ───

    def _ram_pipeline(self, ddr_type: str, max_price: int = None, sort_by: str = "capacity",
                      min_capacity: int = None, max_modules: int = None,
                      max_speed: int = None) -> list:
        """
        RAM aggregation pipeline: inventory + components join.
        components.ram_type ve components.capacity field'larını kullanır.
        sort_by: "capacity" (en yüksek kapasite) veya "price_asc" (en ucuz).
        min_capacity: Minimum GB filtresi (örn. 16 → en az 16GB).
        max_modules: Modul sayısı üst sınırı (MB.memory.slots ≤ kontrolü için).
        max_speed: Anakart chipset'inin desteklediği max hız (MHz). Üzeri kart boşa para.
        Masaüstü build'de SO-DIMM (laptop RAM) varsayılan olarak filtrelenir.
        """
        match_stage = {"component_type": "memory", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}}
        if max_price is not None:
            match_stage["price"] = {"$lte": max_price}

        sort_stage = {"capacity": -1, "price": -1} if sort_by == "capacity" else {"price": 1}

        tech_match = {"tech.ram_type": ddr_type}
        if min_capacity:
            tech_match["tech.capacity"] = {"$gte": min_capacity}
        if max_modules is not None:
            tech_match["tech.modules.quantity"] = {"$lte": max_modules}
        if max_speed is not None:
            # speed null olabilir → null'a izin ver, sadece sayısal ve cap üstü olanları reddet
            tech_match["$or"] = [
                {"tech.speed": {"$lte": max_speed}},
                {"tech.speed": None},
                {"tech.speed": {"$exists": False}},
            ]
        # SO-DIMM (laptop RAM) hariç tut — sadece masaüstü DIMM
        tech_match["tech.form_factor"] = {"$not": {"$regex": "SO.?DIMM", "$options": "i"}}

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

    def _select_best_ram(self, ddr_type: str, max_price: int, max_speed: int = None) -> dict | None:
        """Bütçe dahilinde en yüksek kapasiteli RAM'i getirir.
        max_speed verilirse chipset capi üzeri kartlar reddedilir (fazla para zarar)."""
        from database.mongo_client import get_db
        results = list(get_db()["inventory"].aggregate(
            self._ram_pipeline(ddr_type, max_price, sort_by="capacity", max_speed=max_speed)
        ))
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
            {"$match": {"component_type": "motherboard", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}}},
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
                {"$match": {"component_type": "cpu", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}}},
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
                {"$match": {"component_type": "memory", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}}},
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
        Platform = (socket, ddr_type).

        Skorlama: headroom × DDR_modernity_weight.
        Modernlik agirligi: DDR3=0.4, DDR4=0.7, DDR5=1.0.
        Bu sekilde dusuk butcede DDR4'un ucuz floor'u kazanir; yuksek butcede
        DDR5'in modernlik agirligi headroom'u sokrarak kazanir.
        """
        platforms = self._discover_platforms()
        if not platforms:
            return None

        DDR_MODERNITY = {"DDR3": 0.4, "DDR4": 0.7, "DDR5": 1.0}

        for p in platforms:
            p["headroom"] = budget - p["platform_floor"]
            weight = DDR_MODERNITY.get(p["ddr_type"], 0.7)
            p["score"] = p["headroom"] * weight

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
                # office/general'da iGPU'lu CPU oncelikle: DB'de has_igpu=None oldugu icin
                # isim regex'i kullanilir (Intel non-F, AMD G suffix)
                if use_case.lower() in ("office", "general"):
                    igpu_filter = self._igpu_name_filter(selected_socket)
                    floors[cat] = self._query_inventory("cpu",
                        filters={"socket": selected_socket}, raw_match=igpu_filter, cheapest=True)
                    if not floors[cat]:
                        floors[cat] = self._query_inventory("cpu",
                            filters={"socket": selected_socket}, cheapest=True)
                else:
                    floors[cat] = self._query_inventory("cpu",
                        filters={"socket": selected_socket}, cheapest=True)
            elif cat == "motherboard":
                # GPU-yoğun use_case'lerde low-tier chipset (H610/A520) seçilmesin —
                # VRM throttle riski + Gen3 M.2 slot sınırı.
                mb_raw_floor = None
                if use_case.lower() in GPU_HEAVY_USE_CASES:
                    mb_raw_floor = {"tech.chipset": {"$nin": list(LOW_TIER_CHIPSETS)}}
                floors[cat] = self._query_inventory("motherboard",
                    filters={"socket": selected_socket, "memory.ram_type": target_ddr},
                    raw_match=mb_raw_floor, cheapest=True)
                if not floors[cat] and mb_raw_floor:
                    # Bu sokette mid-tier MB yoksa low-tier'a düş
                    floors[cat] = self._query_inventory("motherboard",
                        filters={"socket": selected_socket, "memory.ram_type": target_ddr},
                        cheapest=True)
            elif cat == "memory":
                floors[cat] = self._get_cheapest_ram_by_ddr(target_ddr)
            elif cat == "gpu":
                # GPU yoğun use_case'lerde Low Profile floor seçilmesin (GT 710 LP gibi)
                exclude_lp = use_case.lower() in GPU_HEAVY_USE_CASES
                floors[cat] = self._query_inventory("gpu", cheapest=True,
                                                    exclude_low_profile=exclude_lp)
            elif cat == "cooler":
                # CPU socket'i destekleyen en ucuz cooler (cpu_sockets array'inde
                # selected_socket geçmeli; AM4 cooler LGA1700 CPU'ya takılmaz).
                floors[cat] = self._query_inventory("cooler", cheapest=True,
                    filters={"cpu_sockets": selected_socket})
                if not floors[cat]:
                    # Fallback: bu socket için cooler bulunamadı, generic en ucuz
                    floors[cat] = self._query_inventory("cooler", cheapest=True)
            else:
                floors[cat] = self._query_inventory(cat, cheapest=True)

        # Bulunamayan kategorileri çıkar
        floors = {k: v for k, v in floors.items() if v}

        # iGPU/dGPU cakisma kontrolu: office/general use_case'te CPU'nun iGPU'su varsa
        # ekstra GPU eklemek anlam disidir, GPU'yu skip et.
        # DB'de has_igpu=None oldugu icin isim suffix'inden tespit
        cpu_floor = floors.get("cpu") or {}
        cpu_has_igpu = self._cpu_has_igpu_from_name(cpu_floor.get("name") or "")
        if cpu_has_igpu and use_case.lower() in ("office", "general"):
            if "gpu" in floors:
                floors.pop("gpu", None)
                all_categories = [c for c in all_categories if c != "gpu"]

        floor_total = total_spend(floors)

        # ─── Office/General iGPU bypass: floor bütçeyi aşıyorsa daha ucuz CPU + GPU dene ───
        # AM4'te tek iGPU CPU 5700G (~11k). Sıkı bütçede bu floor'u patlatır. iGPU SUZ
        # daha ucuz CPU + en ucuz GPU genelde daha düşük toplam üretir.
        if floor_total > budget and use_case.lower() in ("office", "general"):
            cheap_cpu = self._query_inventory("cpu",
                filters={"socket": selected_socket}, cheapest=True)
            cheap_gpu = self._query_inventory("gpu", cheapest=True)
            if cheap_cpu and cheap_gpu:
                alt_total = floor_total - (floors.get("cpu", {}).get("price", 0) or 0) \
                            + cheap_cpu.get("price", 0) + cheap_gpu.get("price", 0)
                if alt_total < floor_total:
                    floors["cpu"] = cheap_cpu
                    floors["gpu"] = cheap_gpu
                    if "gpu" not in all_categories:
                        all_categories.append("gpu")
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

        # GPU ağırlığı: floor + dağıtım sonrası GPU bütçesi yetersiz kalıyor (gaming_30k'da
        # GT 730 seçiliyor). Use case-specific katsayılar — gaming en agresif, rendering
        # RAM'i de önemsediği için daha ılımlı, architecture ortalama. Non-GPU
        # kategorilerden floor'a kadar düşürerek extra topla.
        gpu_boost_params = {
            "gaming":       (0.65, 0.30),
            "rendering":    (0.45, 0.22),
            "architecture": (0.60, 0.30),
            "design":       (0.50, 0.25),  # GPU önemli ama RAM/storage'tan çok da çalmasın
        }
        params = gpu_boost_params.get(use_case.lower())
        # GPU yoğun use_case'lerde CPU bütçenin %25'ini geçmesin (architecture'da
        # i5 14600KF GPU'yu yiyordu). Floor'un altına inemez.
        if params and "cpu" in ceilings:
            cpu_floor_p = floors.get("cpu", {}).get("price", 0)
            ceilings["cpu"] = min(ceilings["cpu"], max(cpu_floor_p, int(budget * 0.25)))
        if params and "gpu" in ceilings:
            distrib_share, budget_share = params
            gpu_floor_price = floors.get("gpu", {}).get("price", 0)
            target_gpu_ceiling = max(
                gpu_floor_price + int(distributable * distrib_share),
                int(budget * budget_share),
            )
            if ceilings["gpu"] < target_gpu_ceiling:
                needed = target_gpu_ceiling - ceilings["gpu"]
                non_gpu = [c for c in ceilings if c != "gpu"]
                slacks = {c: max(0, ceilings[c] - floors.get(c, {}).get("price", 0))
                          for c in non_gpu}
                total_slack = sum(slacks.values())
                if total_slack > 0:
                    take_ratio = min(1.0, needed / total_slack)
                    actually_taken = 0
                    for c in non_gpu:
                        cut = int(slacks[c] * take_ratio)
                        ceilings[c] -= cut
                        actually_taken += cut
                    ceilings["gpu"] += actually_taken

        for cat in priority:
            ceiling = ceilings.get(cat, 0) + unspent
            floor_part = floors.get(cat)
            if not floor_part:
                continue

            # --- RAM: DDR tipi + bütçe içinde en yüksek kapasite, chipset hız capi ---
            if cat == "memory":
                mb_chipset = build.get("motherboard", {}).get("chipset")
                ram_speed_cap = self.chipset_max_ram_speed(mb_chipset, target_ddr)
                best_ram = self._select_best_ram(target_ddr, int(ceiling), max_speed=ram_speed_cap)
                if not best_ram:
                    # Cap içinde bulunamadı — capsiz dene (eski davranış)
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
                    # Anakartı da platform kısıtlarıyla güncelle (low-tier exclude)
                    mobo_ceiling = ceilings.get("motherboard", 0) + max(unspent, 0)
                    mb_raw_upg = None
                    if use_case.lower() in GPU_HEAVY_USE_CASES:
                        mb_raw_upg = {"tech.chipset": {"$nin": list(LOW_TIER_CHIPSETS)}}
                    mobo_better = self._query_inventory("motherboard", int(mobo_ceiling),
                        filters={"socket": selected_socket, "memory.ram_type": target_ddr},
                        raw_match=mb_raw_upg)
                    if not mobo_better and mb_raw_upg:
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
            # GPU yoğun use_case'lerde Low Profile kartları reddet (mid-tower'da gereksiz).
            exclude_lp = (cat == "gpu" and use_case.lower() in gpu_boost_params)
            # Cooler için CPU socket eşleşmesi şart (AM4 cooler LGA1700 CPU'ya takılmaz).
            cat_filters = {"cpu_sockets": selected_socket} if cat == "cooler" else None
            # Storage için NVMe-first: GPU-yoğun use_case + MB'nin m2_slots'u doluysa
            # önce M.2 NVMe ara; bulamazsan SATA'ya düş (550 MB/s vs 3000+ MB/s).
            storage_raw = None
            if cat == "storage" and use_case.lower() in GPU_HEAVY_USE_CASES:
                m2_slots = build.get("motherboard", {}).get("m2_slots") or []
                if m2_slots:
                    storage_raw = {
                        "tech.form_factor": {"$regex": r"^M\.2", "$options": "i"},
                        "tech.interface": {"$regex": "PCIe", "$options": "i"},
                    }
            better = self._query_inventory(cat, int(ceiling), filters=cat_filters,
                                            raw_match=storage_raw,
                                            exclude_low_profile=exclude_lp)
            if not better and storage_raw:
                # M.2 NVMe bulunamadı → fallback: filtersiz (SATA dahil)
                better = self._query_inventory(cat, int(ceiling), filters=cat_filters)
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
        # FAZ 4b: Storage MB-Compatibility Filtre
        # MB seçilince storage'ı MB'nin m2_slots[].size + sata desteğine göre revize et
        # ══════════════════════════════════════════

        mb_obj = build.get("motherboard", {})
        m2_slots = mb_obj.get("m2_slots") or []
        sd = mb_obj.get("storage_devices") or {}
        has_sata = (sd.get("sata_6_gb_s") or 0) + (sd.get("sata_3_gb_s") or 0) > 0
        # MB'nin desteklediği M.2 boyutlarını topla (örn ["2242-2260", "2280"])
        supported_m2_sizes = {(s.get("size") or "").strip() for s in m2_slots if s.get("size")}

        storage_obj = build.get("storage", {})
        storage_ff = (storage_obj.get("form_factor") or "").strip()
        storage_compatible = True

        if storage_ff.upper().startswith("M.2"):
            target_size = storage_ff.replace("M.2-", "").strip()
            storage_compatible = any(
                target_size in ss or ss in target_size or
                ("-" in ss and target_size in ss.split("-"))
                for ss in supported_m2_sizes
            )
        elif '"' in storage_ff:
            storage_compatible = has_sata or sum(sd.values()) == 0  # sata_count=0 ise tolere
        elif storage_ff.lower() == "msata":
            storage_compatible = False

        if not storage_compatible:
            # MB'nin desteklediği boyutta SSD ara
            from database.mongo_client import get_db
            ceiling = ceilings.get("storage", 0) + 1000
            current_price = storage_obj.get("price", 0)
            # Önce MB'nin destekledigi en yaygın size (2280 varsa onu, yoksa ilkini)
            preferred_sizes = ["2280", "2242", "2230"]
            chosen_ff = None
            for ps in preferred_sizes:
                if any(ps in ss for ss in supported_m2_sizes):
                    chosen_ff = f"M.2-{ps}"
                    break
            if not chosen_ff and supported_m2_sizes:
                # Fallback: ilk slot size'in son segmenti
                first = next(iter(supported_m2_sizes))
                last_seg = first.split("-")[-1]
                chosen_ff = f"M.2-{last_seg}"
            if not chosen_ff and has_sata:
                chosen_ff = '2.5"'

            if chosen_ff:
                replacement = self._query_inventory(
                    "storage", max_price=int(max(ceiling, current_price)),
                    filters={"form_factor": chosen_ff}
                )
                if replacement:
                    build["storage"] = replacement

        # ══════════════════════════════════════════
        # FAZ 4c: RAM Slot Sayısı Filtre
        # MB'nin slot sayısı modules.quantity'den azsa daha az modüllü kit ara
        # ══════════════════════════════════════════

        mb_memory = mb_obj.get("memory") or {}
        mb_slots = mb_memory.get("slots")
        ram_obj = build.get("memory", {})
        ram_modules = ram_obj.get("modules") if isinstance(ram_obj.get("modules"), dict) else {}
        ram_qty = ram_modules.get("quantity")

        if mb_slots and ram_qty and ram_qty > mb_slots:
            from database.mongo_client import get_db
            current_cap = ram_obj.get("capacity", 0)
            current_price = ram_obj.get("price", 0)
            # Aynı kapasiteden basla, yoksa kademeli olarak yariya dusur (32→16→8)
            replacement = None
            for cap_target in [current_cap, current_cap // 2, current_cap // 4]:
                if cap_target <= 0:
                    break
                results = list(get_db()["inventory"].aggregate([
                    {"$match": {"component_type": "memory", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True},
                                "price": {"$lte": int(current_price * 1.5)}}},
                    {"$lookup": {"from": "components", "localField": "component_id",
                                 "foreignField": "component_id", "as": "tech"}},
                    {"$unwind": "$tech"},
                    {"$match": {
                        "tech.ram_type": target_ddr,
                        "tech.capacity": cap_target,
                        "tech.modules.quantity": {"$lte": mb_slots},
                        "tech.form_factor": {"$not": {"$regex": "SO.?DIMM", "$options": "i"}},
                    }},
                    {"$sort": {"tech.modules.quantity": -1, "price": 1}},
                    {"$limit": 1},
                    {"$addFields": {
                        "name": {"$ifNull": ["$tech.name", "$retailer_title"]},
                        "ram_type": "$tech.ram_type",
                        "capacity": "$tech.capacity",
                        "speed": "$tech.speed",
                        "modules": "$tech.modules",
                        "form_factor": "$tech.form_factor",
                    }},
                    {"$project": {"tech": 0, "_id": 0}},
                ]))
                if results:
                    replacement = results[0]
                    break
            if replacement:
                build["memory"] = replacement

        # ══════════════════════════════════════════
        # FAZ 5: Son kontroller
        # ══════════════════════════════════════════

        # İsim normalizasyonu
        for cat, part in build.items():
            part["name"] = self._name_of(part)

        spent = total_spend(build)
        warnings = []

        # Tek modül RAM (single-channel) tespit edilirse aynı toplam kapasitede
        # 2-modüllü kit varsa öner (data-driven: modules.quantity=2 olan eşit kapasite ara).
        ram_obj = build.get("memory", {})
        modules_info = ram_obj.get("modules") if isinstance(ram_obj.get("modules"), dict) else None
        if modules_info and modules_info.get("quantity") == 1:
            from database.mongo_client import get_db
            current_cap = ram_obj.get("capacity", 0)
            current_price = ram_obj.get("price", 0)
            # Aynı DDR + aynı kapasite + 2 modül + uygun fiyat
            dual_kit = list(get_db()["inventory"].aggregate([
                {"$match": {"component_type": "memory", "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True},
                            "price": {"$lte": int(current_price * 1.5)}}},
                {"$lookup": {"from": "components", "localField": "component_id",
                             "foreignField": "component_id", "as": "tech"}},
                {"$unwind": "$tech"},
                {"$match": {
                    "tech.ram_type": target_ddr,
                    "tech.capacity": current_cap,
                    "tech.modules.quantity": 2,
                    "tech.form_factor": {"$not": {"$regex": "SO.?DIMM", "$options": "i"}},
                }},
                {"$sort": {"price": 1}},
                {"$limit": 1},
                {"$addFields": {
                    "name": {"$ifNull": ["$tech.name", "$retailer_title"]},
                    "ram_type": "$tech.ram_type",
                    "capacity": "$tech.capacity",
                    "speed": "$tech.speed",
                    "modules": "$tech.modules",
                    "form_factor": "$tech.form_factor",
                }},
                {"$project": {"tech": 0, "_id": 0}},
            ]))
            if dual_kit:
                cand = dual_kit[0]
                # Bütçe aşmıyorsa direkt değiştir
                price_diff = cand["price"] - current_price
                if budget - spent >= price_diff:
                    build["memory"] = cand
                    build["memory"]["name"] = self._name_of(build["memory"])
                    spent = total_spend(build)
                else:
                    warnings.append(
                        f"⚠️ TEK MODÜL: {current_cap}GB tek modül seçildi. Aynı kapasitede "
                        f"2x kit ({cand.get('name', '?')[:40]}) {cand['price']:,} TL — "
                        f"bütçeye {price_diff:,} TL ek gerek."
                    )

        # ══════════════════════════════════════════
        # FAZ 6: Final Rebalance — kalan butce > %5 ise upgrade
        # ══════════════════════════════════════════

        spent = total_spend(build)
        remaining = budget - spent
        if remaining > budget * 0.05:
            upgrade_priority = ["gpu", "cpu", "memory", "storage", "psu", "cooler", "case"]
            for cat in upgrade_priority:
                if cat not in build:
                    continue
                current = build[cat]
                if not isinstance(current, dict):
                    continue
                # GPU office/general iGPU skip durumunda yok zaten
                new_ceiling = current.get("price", 0) + remaining
                cat_filters = None
                if cat == "cpu":
                    cat_filters = {"socket": selected_socket}
                    if use_case.lower() in ("office", "general"):
                        igpu_raw = self._igpu_name_filter(selected_socket)
                        better = self._query_inventory(cat, int(new_ceiling),
                            filters=cat_filters, raw_match=igpu_raw)
                        if better and better.get("price", 0) > current.get("price", 0):
                            delta = better["price"] - current["price"]
                            if delta <= remaining:
                                build[cat] = better
                                remaining -= delta
                                spent += delta
                        continue
                elif cat == "motherboard":
                    cat_filters = {"socket": selected_socket, "memory.ram_type": target_ddr}
                elif cat == "memory":
                    # RAM upgrade: chipset hız capi uygula (DDR5-6000 H610'da boşa para)
                    mb_chipset = build.get("motherboard", {}).get("chipset")
                    ram_speed_cap = self.chipset_max_ram_speed(mb_chipset, target_ddr)
                    upgraded = self._select_best_ram(target_ddr, int(new_ceiling),
                                                     max_speed=ram_speed_cap)
                    if upgraded and upgraded.get("price", 0) > current.get("price", 0):
                        delta = upgraded["price"] - current["price"]
                        if delta <= remaining:
                            build[cat] = upgraded
                            remaining -= delta
                            spent += delta
                    continue
                elif cat == "cooler":
                    # Cooler upgrade'inde de socket eşleşmesi şart.
                    cat_filters = {"cpu_sockets": selected_socket}
                exclude_lp = (cat == "gpu" and use_case.lower() in GPU_HEAVY_USE_CASES)
                # MB rebalance upgrade'de de low-tier chipset exclude (GPU yoğun use_case)
                rb_raw = None
                if cat == "motherboard" and use_case.lower() in GPU_HEAVY_USE_CASES:
                    rb_raw = {"tech.chipset": {"$nin": list(LOW_TIER_CHIPSETS)}}
                # Storage rebalance upgrade'de NVMe-first
                if cat == "storage" and use_case.lower() in GPU_HEAVY_USE_CASES:
                    if build.get("motherboard", {}).get("m2_slots"):
                        rb_raw = {
                            "tech.form_factor": {"$regex": r"^M\.2", "$options": "i"},
                            "tech.interface": {"$regex": "PCIe", "$options": "i"},
                        }
                better = self._query_inventory(cat, int(new_ceiling),
                    filters=cat_filters, raw_match=rb_raw,
                    exclude_low_profile=exclude_lp)
                if not better and cat == "storage" and rb_raw:
                    # NVMe yoksa SATA fallback
                    better = self._query_inventory(cat, int(new_ceiling), filters=cat_filters)
                if better and better.get("price", 0) > current.get("price", 0):
                    delta = better["price"] - current["price"]
                    if delta <= remaining:
                        build[cat] = better
                        remaining -= delta
                        spent += delta
                        if remaining < budget * 0.05:
                            break

        # Offers enrichment: her parca icin component_id'nin tum retailer kayitlarini topla
        from database.mongo_client import get_inventory_collection
        inv = get_inventory_collection()
        for cat, part in build.items():
            if not isinstance(part, dict):
                continue
            url = part.get("url")
            if not url:
                continue
            # Bu parcanin component_id'si — inventory'den al
            inv_doc = inv.find_one({"url": url}, {"component_id": 1})
            cid = inv_doc.get("component_id") if inv_doc else None
            if not cid:
                continue
            offers = list(inv.find(
                {"component_id": cid, "in_stock": True, "is_accessory": {"$ne": True}, "is_laptop": {"$ne": True}},
                {"_id": 0, "retailer": 1, "price": 1, "url": 1, "retailer_title": 1}
            ).sort("price", 1))
            if len(offers) > 1:
                part["offers"] = offers
                # En ucuzu top-level price/url/retailer'a yaz
                cheapest = offers[0]
                part["price"] = cheapest["price"]
                part["url"] = cheapest["url"]
                part["retailer"] = cheapest["retailer"]

        # Offers'tan sonra spent yeniden hesapla (en ucuza guncellendi)
        spent = total_spend(build)

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

        # ─── KONTROL 0b: Storage ↔ Anakart Form Factor Uyumu ───
        if storage and mobo:
            s_errors, s_warnings = self._check_storage_compat(mobo, storage)
            errors.extend(s_errors)
            warnings.extend(s_warnings)

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

        # ─── KONTROL 2b: Memory form_factor (Masaüstü vs Laptop) ───
        if ram:
            errors.extend(self._check_memory_form_factor(ram))

        # ─── KONTROL 2c: Memory tek modül (Single-Channel) Uyarısı ───
        if ram:
            warnings.extend(self._check_memory_kit(ram))

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

        # ─── KONTROL 6: PSU Güç Yeterliliği + Oversize ───
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
                # Oversize: gerekli minimumun 2 katından fazla = bütçe israfı
                if psu_watt > required_watt * 2:
                    warnings.append(
                        f"💡 PSU AŞIRI BÜYÜK: {psu_watt}W seçildi, sistem CPU+GPU TDP'sine göre "
                        f"~{required_watt}W yeterli (2 katından fazla). Daha küçük PSU ile aynı verim, "
                        f"tasarruf edilen bütçe başka parçaya kanalize edilebilir."
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

        # ─── KONTROL 9: Cooler ↔ CPU Socket Uyumu ───
        # Cooler.cpu_sockets array'inde CPU socket'i geçmeli. AM4 cooler LGA1700
        # CPU'ya takılmaz. DB'de cpu_sockets %99 dolu (BuildCores reference data).
        if cpu and cooler:
            cpu_socket_str = (cpu.get("socket") or "").strip()
            cooler_sockets = cooler.get("cpu_sockets") or []
            cooler_name = cooler.get("name", "")
            if cpu_socket_str and cooler_sockets and isinstance(cooler_sockets, list):
                # Normalize edip karşılaştır (boşluksuz/boşluklu varyantlar)
                cpu_norm = cpu_socket_str.replace(" ", "").upper()
                cooler_norm = [s.replace(" ", "").upper() for s in cooler_sockets if s]
                if cpu_norm not in cooler_norm:
                    errors.append(
                        f"⛔ COOLER SOKET UYUMSUZLUĞU: Soğutucu '{cooler_name[:50]}' "
                        f"{cooler_sockets} soketleri destekliyor, CPU ise {cpu_socket_str} "
                        f"soketinde. Soğutucu fiziksel olarak takılamaz."
                    )

        # ─── KONTROL 8: Cooler ↔ Kasa Fanı Mismatch (güvenlik ağı) ───
        # Önceki feedback: "Cougar AQUA Water" adıyla seçilen ürün gerçekte kasa fanı.
        # Pattern + URL filter atlasa bile cooler title'ında "fan" var ve gerçek
        # cooler keyword'leri yoksa → kullanıcıya uyar.
        if cooler:
            cooler_text = (cooler.get("name") or "").lower()
            cooler_url = (cooler.get("url") or "").lower()
            real_cooler_keywords = [
                "cooler", "sıvı", "sivi", "aio", "liquid",
                "hava soğutmalı", "hava sogutmali", "air cooler",
                "radyatör", "radyator", "radiator", "tower",
                "cpu soğutucu", "cpu sogutucu", "işlemci soğutucu", "islemci sogutucu",
            ]
            chassis_indicators = [
                "kasa fan", "chassis fan", "case fan", "system fan",
                "kasa-fan", "case-fan", "chassis-fan",
            ]
            looks_chassis = any(ind in cooler_text or ind in cooler_url for ind in chassis_indicators)
            looks_real = any(kw in cooler_text for kw in real_cooler_keywords)
            if looks_chassis and not looks_real:
                errors.append(
                    f"⛔ COOLER YANLIŞ ÜRÜN: Seçilen '{cooler.get('name', '?')[:60]}' "
                    f"CPU soğutucusu değil, kasa fanı. CPU thermal throttle'a girer ve "
                    f"sistem birkaç saniyede shutdown olur."
                )
            elif "fan" in cooler_text and not looks_real and "120mm" in cooler_text:
                # Daha gevşek heuristic: title'da sadece "fan" var, cooler keyword yok
                warnings.append(
                    f"⚠️ COOLER ŞÜPHELİ: '{cooler.get('name', '?')[:60]}' CPU soğutucusu "
                    f"olduğu net değil. Ürün dökümanından doğrulayın."
                )

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    # ─── Yardımcı Uyumluluk Kontrolleri (data-driven) ───

    @staticmethod
    def _check_storage_compat(mobo: dict, storage: dict) -> tuple:
        """Storage form_factor anakartın gerçek slot yapısıyla eşleşiyor mu?
        DB field'lari: motherboard.m2_slots[].size, motherboard.storage_devices.sata_*
        Returns (errors, warnings) — DB veri eksiklikleri warnings'a düşer, kesin uyumsuzluklar errors'a."""
        errors = []
        warnings = []
        s_ff = (storage.get("form_factor") or "").strip()
        s_name = storage.get("name") or storage.get("retailer_title") or "?"
        if not s_ff:
            return errors, warnings

        # mSATA: hiçbir modern motherboard schema'sında msata field'ı yok (kesin uyumsuz)
        if s_ff.lower() == "msata":
            errors.append(
                f"⛔ STORAGE UYUMSUZ: '{s_name[:60]}' mSATA form factor'unda. "
                f"Modern anakartlarda mSATA slot yok — fiziksel olarak takılamaz."
            )
            return errors, warnings

        # M.2-XXXX (NVMe/SATA M.2) — kesin kontrol (m2_slots datasi guvenilir, %99 dolu)
        if s_ff.upper().startswith("M.2"):
            m2_slots = mobo.get("m2_slots") or []
            if not m2_slots:
                errors.append(
                    f"⛔ STORAGE UYUMSUZ: '{s_name[:60]}' M.2 ({s_ff}) format, "
                    f"ancak seçilen anakartta M.2 slot bulunmuyor."
                )
                return errors, warnings
            target_size = s_ff.replace("M.2-", "").strip()
            for slot in m2_slots:
                slot_size = (slot.get("size") or "").strip()
                if target_size in slot_size or slot_size in target_size:
                    return errors, warnings
                if "-" in slot_size and target_size in slot_size.split("-"):
                    return errors, warnings
            available = ", ".join(s.get("size", "?") for s in m2_slots)
            errors.append(
                f"⛔ STORAGE BOYUT UYUMSUZ: SSD {s_ff}, anakartın M.2 slot'ları "
                f"{available} boyutlarını destekliyor."
            )
            return errors, warnings

        # 2.5" / 3.5" (SATA) — yumusak kontrol (DB'de %35 MB'de sata_count=0 yanlis kayit)
        if '"' in s_ff:
            sd = mobo.get("storage_devices") or {}
            sata_count = (sd.get("sata_6_gb_s") or 0) + (sd.get("sata_3_gb_s") or 0)
            if sata_count == 0:
                warnings.append(
                    f"⚠️ SATA PORT BELIRSIZ: '{s_name[:60]}' {s_ff} SATA disk, "
                    f"anakartın SATA bilgisi DB'de eksik (sata_count=0). Çoğu anakartta vardır, "
                    f"ürün dökümanından doğrulayın."
                )
            return errors, warnings

        return errors, warnings

    @staticmethod
    def _check_memory_form_factor(ram: dict) -> list:
        """Masaüstü build'de SO-DIMM (laptop RAM) seçildiyse hata.
        DB'de form_factor degerleri: '288-pin DIMM' (DDR5), '240-pin DIMM' (DDR4),
        '262-pin SO-DIMM' (DDR5 laptop), '260-pin SO-DIMM' (DDR4 laptop), '204-pin SO-DIMM' (DDR3 laptop)"""
        errors = []
        ff_norm = (ram.get("form_factor") or "").upper().replace(" ", "").replace("-", "")
        if "SODIMM" in ff_norm:
            ram_name = ram.get("name") or ram.get("retailer_title") or "?"
            errors.append(
                f"⛔ LAPTOP RAM: '{ram_name[:60]}' SO-DIMM (laptop RAM, form_factor={ram.get('form_factor')}), "
                f"masaüstü anakarta takılmaz. DIMM RAM seçilmeli."
            )
        return errors

    @staticmethod
    def _check_memory_kit(ram: dict) -> list:
        """RAM modules.quantity == 1 ise single-channel uyarısı."""
        warnings = []
        modules = ram.get("modules")
        if isinstance(modules, dict):
            qty = modules.get("quantity")
            cap = modules.get("capacity_gb") or ram.get("capacity")
            if qty == 1:
                warnings.append(
                    f"⚠️ TEK MODÜL RAM: {cap}GB tek modül seçildi (1x{cap}GB). "
                    f"Dual-channel için 2 modül gerekir — şu hâliyle bellek bant genişliği yarıya düşer "
                    f"(oyun/render ~%10-30 perf kaybı). 2x kit veya ikinci modül takılmalı."
                )
        return warnings


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
        # Bütçe aşımı varken upgrade önermek anlamsız — bütçe içinde kalmalıyız.
        remaining = target_budget - current_spend
        budget_exceeded = target_budget > 0 and current_spend > target_budget
        if not budget_exceeded and remaining > target_budget * 0.03:
            for cat in ["gpu", "cpu", "storage"]:
                current_part = selected.get(cat)
                if not current_part: continue

                max_price = current_part.get("price", 0) + remaining
                better = self.logic.get_best_part_for_budget(cat, int(max_price))

                if not better:
                    continue
                # Aynı parçayı "fırsat" olarak gösterme — component_id veya isim aynıysa skip.
                cur_id = current_part.get("component_id")
                new_id = better.get("component_id")
                same_part = (cur_id and new_id and cur_id == new_id) or \
                            (better.get("name") == current_part.get("name"))
                if same_part:
                    continue
                # Anlamlı bir fiyat farkı (≥%10) gerekli — küçük dalgalanmalar performans
                # üstünlüğü garantilemiyor (price-sorted, performans değil).
                if better.get("price", 0) < current_part.get("price", 0) * 1.10:
                    continue

                new_warnings.append(
                    f"✨ FIRSAT: {cat.upper()} kategorisinde {better.get('name')} modeline "
                    f"geçebilirsiniz. Bütçeniz buna yetiyor."
                )
                break

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
