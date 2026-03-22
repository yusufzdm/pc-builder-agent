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
        "storage": "internal-hard-drive",
        "cooler": "cpu-cooler"
    }

    ALLOCATION_PROFILES = {
        "gaming": {
            "gpu": 0.38, "cpu": 0.18, "motherboard": 0.10,
            "memory": 0.09, "storage": 0.08, "case": 0.06, "psu": 0.07, "cooler": 0.04
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

    # ─── Bütçe ve Optimizasyon Yardımcıları ───

    def get_best_part_for_budget(self, component_type: str, max_price: int, filters: dict = None) -> dict:
        """
        MongoDB'den belirli bütçeye uygun en iyi (en pahalı) parçayı getirir.
        """
        from database.hybrid_search import safe_search
        
        # Filtreleri sorgu metnine ekle (vektör araması için ipucu)
        query = ""
        if filters:
            query = " ".join([str(v) for v in filters.values() if v])
        
        # Kategori haritalama
        db_type = self.CATEGORY_MAP.get(component_type, component_type)
        
        # safe_search çağır (max_results=5 getirip içinden en pahalıyı seçelim)
        results = safe_search(query, db_type, max_price=max_price, max_results=5)
        
        if not results:
            return None
            
        # Fiyata göre azalan sırala ve en üsttekini al
        results.sort(key=lambda x: x.get("price", 0), reverse=True)
        return results[0]

    def optimize_build(self, budget: int, use_case: str = "general", custom_allocations: dict = None) -> dict:
        """
        Bütçe ve kullanım senaryosuna göre optimal sistem toplar.
        Kalan bütçeyi iteratif olarak daha iyi parçalara yatırır.
        """
        # Profil al
        profile = custom_allocations or self.ALLOCATION_PROFILES.get(use_case.lower(), self.ALLOCATION_PROFILES["general"])
        
        # İlk bütçe dağılımı
        allocations = {cat: int(budget * pct) for cat, pct in profile.items()}
        
        build = {}
        selected_socket = None
        selected_ram_type = None
        
        # 1. İlk geçiş - Temel parçaları seç
        # Öncelik sırası: Mobo -> CPU -> RAM -> Diğerleri
        ordered_categories = ["motherboard", "cpu", "memory", "gpu", "storage", "cooler", "case"]
        
        for cat in ordered_categories:
            filters = {}
            if cat == "cpu" and selected_socket: filters["socket"] = selected_socket
            if cat == "memory" and selected_ram_type: filters["type"] = selected_ram_type
            
            part = self.get_best_part_for_budget(cat, allocations.get(cat, 0), filters=filters)
            if part:
                build[cat] = part
                if cat == "motherboard":
                    selected_socket = part.get("socket")
                    selected_ram_type = part.get("memory_type")
                elif cat == "cpu" and not selected_socket:
                    selected_socket = part.get("socket")

        # PSU (Özel hesaplama gerektirir)
        cpu = build.get("cpu", {})
        gpu = build.get("gpu", {})
        cpu_tdp = int(cpu.get("tdp") or cpu.get("tech_specs", {}).get("tdp", 65))
        gpu_tdp = int(gpu.get("tdp") or gpu.get("tech_specs", {}).get("tdp", 200))
        min_psu_watt = self.calculate_min_psu(cpu_tdp, gpu_tdp)
        
        psu = self.get_best_part_for_budget("psu", allocations.get("psu", int(budget * 0.07)), filters={"wattage": min_psu_watt})
        if not psu: # Bütçe yetmezse en ucuz uygun olanı al
            from database.hybrid_search import safe_search
            psu_results = safe_search(str(min_psu_watt), self.CATEGORY_MAP["psu"], max_price=None, max_results=10)
            suitable = [p for p in psu_results if (p.get("wattage") or p.get("tech_specs", {}).get("wattage", 0)) >= min_psu_watt]
            if suitable:
                suitable.sort(key=lambda x: x.get("price", 0))
                psu = suitable[0]
        
        if psu: build["psu"] = psu

        # 2. İTERATİF UPGRADE
        def get_total_spend(b):
            return sum(item.get("price", 0) for item in b.values() if isinstance(item, dict))

        current_spend = get_total_spend(build)
        remaining = budget - current_spend
        
        priority = ["gpu", "cpu", "storage", "memory", "cooler", "motherboard", "case"]
        
        while remaining > budget * 0.05:
            upgraded = False
            for cat in priority:
                current_part = build.get(cat)
                if not current_part: continue
                
                max_new_price = current_part.get("price", 0) + remaining
                filters = {}
                if cat == "cpu": filters["socket"] = selected_socket
                elif cat == "motherboard": filters["socket"] = selected_socket
                elif cat == "memory": filters["type"] = selected_ram_type
                elif cat == "psu": filters["wattage"] = min_psu_watt
                
                better = self.get_best_part_for_budget(cat, int(max_new_price), filters=filters)
                if better and better.get("price", 0) > current_part.get("price", 0):
                    build[cat] = better
                    remaining -= (better["price"] - current_part["price"])
                    upgraded = True
                    break
            if not upgraded: break

        return {
            "selected_components": build,
            "total_spend": get_total_spend(build),
            "remaining_budget": budget - get_total_spend(build),
            "use_case": use_case
        }

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
            cpu_socket = cpu.get("socket") or cpu.get("tech_specs", {}).get("socket")
            mobo_socket = mobo.get("socket") or mobo.get("tech_specs", {}).get("socket")
            if cpu_socket and mobo_socket and cpu_socket != mobo_socket:
                errors.append(
                    f"⛔ SOKET UYUMSUZLUĞU: İşlemci {cpu_socket} soket kullanıyor, "
                    f"Anakart ise {mobo_socket} soket. Birlikte çalışamazlar."
                )

        # ─── KONTROL 2: Anakart ↔ RAM Tipi ───
        if mobo and ram:
            mobo_mem = mobo.get("memory_type") or mobo.get("tech_specs", {}).get("memory_type")
            ram_type = ram.get("type") or ram.get("tech_specs", {}).get("type")
            if mobo_mem and ram_type and mobo_mem != ram_type:
                errors.append(
                    f"⛔ RAM UYUMSUZLUĞU: Anakart {mobo_mem} destekliyor, "
                    f"seçilen RAM {ram_type} tipinde."
                )
            
            # --- YENİ: RAM Kapasite ve Slot Kontrolü ---
            max_mem = mobo.get("max_memory") or mobo.get("tech_specs", {}).get("max_memory", 128)
            ram_cap = ram.get("capacity") or ram.get("tech_specs", {}).get("capacity", 0)
            if ram_cap > max_mem:
                errors.append(f"⛔ RAM KAPASİTE HATASI: Anakart en fazla {max_mem}GB destekliyor, seçilen RAM {ram_cap}GB.")
            
            mobo_slots = int(mobo.get("memory_slots") or mobo.get("tech_specs", {}).get("memory_slots", 4))
            # RAM isminden (örn: 2x16GB) kaç modül olduğunu bulmaya çalış
            ram_name = ram.get("name", "").lower()
            stick_count = 1
            if "2x" in ram_name: stick_count = 2
            elif "4x" in ram_name: stick_count = 4
            
            if stick_count > mobo_slots:
                errors.append(f"⛔ RAM SLOT HATASI: Anakartta {mobo_slots} slot var, seçilen RAM kiti {stick_count} modül içeriyor.")

        # ─── KONTROL 3: Kasa ↔ Anakart (Form Factor) ───
        if case and mobo:
            case_type = (case.get("type") or "").lower()
            mobo_ff = (mobo.get("form_factor") or "").lower()
            
            # Form faktör hiyerarşisi
            ff_hierarchy = {
                "atx": 3,
                "micro atx": 2,
                "mini itx": 1
            }
            
            # Kasanın en büyük hangi anakartı desteklediğini bul
            case_limit = 3 # Varsayılan ATX
            if "mini itx" in case_type: case_limit = 1
            elif "microatx" in case_type or "micro atx" in case_type: case_limit = 2
            
            mobo_val = ff_hierarchy.get(mobo_ff, 0)
            if mobo_val > case_limit:
                errors.append(
                    f"⛔ FİZİKSEL UYUMSUZLUK: Seçilen anakart ({mobo_ff.upper()}) "
                    f"seçilen kasaya ({case_type.upper()}) sığmaz. Daha büyük bir kasa seçin."
                )

        # ─── KONTROL 4: Kasa ↔ GPU Boyutu ───
        if case and gpu:
            max_gpu_len = case.get("max_gpu_length") or case.get("tech_specs", {}).get("max_gpu_length", 999)
            gpu_len = gpu.get("length") or gpu.get("tech_specs", {}).get("length", 0)
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

        # ─── KONTROL 5: Kasa ↔ Sıvı Soğutucu (Radiator) ───
        if case and cooler:
            cooler_size = cooler.get("size") # 120, 240, 360 veya None
            if cooler_size:
                case_type = (case.get("type") or "").lower()
                try:
                    cooler_size = int(cooler_size)
                    # Basit kural: Micro ATX kasalar genellikle max 240mm destekler
                    if "micro" in case_type and cooler_size > 240:
                        errors.append(
                            f"⛔ SOĞUTUCU SIĞMIYOR: {cooler_size}mm sıvı soğutucu bu kasaya büyük gelebilir. "
                            f"Maksimum 240mm önerilir."
                        )
                except: pass

        # ─── KONTROL 6: PSU Güç Yeterliliği ───
        if psu:
            cpu_tdp = cpu.get("tdp") or cpu.get("tech_specs", {}).get("tdp", 65)
            gpu_tdp = gpu.get("tdp") or gpu.get("tech_specs", {}).get("tdp", 200)
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
            cpu_tdp = int(cpu.get("tdp") or cpu.get("tech_specs", {}).get("tdp", 65))
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
