"""
database/accessory_filter.py
Bir bileşenin "PC build için kullanılamaz aksesuar/yanlış-kategorideki ürün"
olup olmadığını tespit eden merkezi helper.

Kullanım:
    from database.accessory_filter import is_accessory
    is_acc, reason = is_accessory(name, retailer_title, url, component_type)
    if is_acc:
        # bu kayıt build'e dahil edilmemeli — DB'ye yazma / search'ten çıkar

Mekanizma:
  - Mevcut DB temizliği (scripts/cleanup_accessories.py)
  - Yeni scrape sonrası ER apply (scrapers/entity_resolution.py:apply_matched) — SKIP
  - Initial seed (database/seed_database.py) — SKIP

Not: "laptop bileşeni" KAVRAMSAL OLARAK FARKLIDIR (doğru kategori, masaüstü
build'e uygun değil) — onlar için ayrı `database/laptop_filter.py` var.
"""

import re

# ─── Kategori başına aksesuar pattern'leri (lowercase substring + bağlam) ───
ACCESSORY_PATTERNS = {
    "case": [
        # Sadece spesifik aksesuar etiketleri — generic kelimeler (örn " stand ")
        # gerçek kasa açıklamalarında ("Tower 300 ... Support Up Stand alone") false
        # positive yaratır. Türkçe "kasa standı" zaten ürün etiketi.
        "kasa standı", "kasa stand", "kasa altı", "kasa altligi",
        "kasa lambasi", "kabin tutma", "kasaya tutturma",
        "kasa kabine", "kasa pad",
    ],
    "cooler": [
        # Soğutucu aksesuarları (montaj kiti, termal pasta vs)
        "termal pasta", "thermal paste", "termal macun",
        "fan adaptör", "fan kablosu",
        "fan controller", "fan kontrol kiti", "fan kontrol modül",
        "soğutucu montaj", "cooler bracket", "soğutucu kit",
        "fan filtresi", "fan filter", "toz filtresi",
        "montaj kiti",
        # Kasa fanı (cooler kategorisinde olmamalı, ER mismatch)
        "kasa fan", "chassis fan", "case fan", "system fan",
        "kasa-fan",  # URL pattern
    ],
    "storage": [
        "ssd kutu", "ssd enclosure", "ssd kasa",
        "harici disk kutu", "external enclosure",
        "ssd adaptör", "ssd montaj", "ssd bracket",
        "m.2 adaptör", "m.2 to sata", "m.2 to usb",
        "ssd kablo", "sata kablo", "sata cable",
        "hdd dock", "ssd dock",
    ],
    "memory": [
        "ram heatsink", "ram soğutucu",
        "ram lighting", "ram led",
    ],
    "psu": [
        "psu uzatma", "psu kablo", "psu cable extension",
        "atx adaptör", "atx kablo",
        "8 pin uzatma", "24 pin uzatma",
        "kablo kit", "cable kit", "modular kabin",
    ],
    "gpu": [
        "gpu destek", "vga destek", "ekran karti destek",
        "gpu tutucu", "vga tutucu",
        "riser kablo", "riser cable", "pcie riser",
        "gpu lambasi",
    ],
    "cpu": [
        "cpu socket koruyucu", "socket cover",
        "cpu protector",
    ],
    "motherboard": [],
}

# Bağlam exclude — "fan" geçen ama "cooler/sıvı/AIO/hava soğutmalı/radyatör/tower"
# da geçen ürünler kasa fanı DEĞİL, gerçek CPU cooler. False positive koruması.
COOLER_CONTEXT_NEGATIVE = [
    "cooler", "sivi", "sıvı", "aio", "liquid",
    "hava soğutmalı", "hava sogutmali", "air cooler",
    "radyatör", "radyator", "radiator",
    "cpu soğutucu", "cpu sogutucu", "işlemci soğutucu", "islemci sogutucu",
    "soğutmalı cpu", "sogutmali cpu",
    "tower",  # Tower-style hava cooler
]

# URL'de kesin işaret eden pattern'ler (override negative context)
URL_DEFINITE_ACCESSORY = {
    "cooler": ["kasa-fan", "case-fan", "chassis-fan"],
}


def _normalize(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower()).strip()


def is_accessory(name: str = None, retailer_title: str = None,
                 url: str = None, component_type: str = None) -> tuple[bool, str]:
    """
    Bir kaydın PC build'e uygun olmayan aksesuar/yanlış-kategori ürün
    olup olmadığını tespit eder.

    Returns:
        (is_accessory: bool, reason: str)
    """
    text = _normalize(" ".join(filter(None, [name, retailer_title])))
    url_norm = _normalize(url or "")
    cat = (component_type or "").lower()

    # 1. URL'de kesin işaret varsa override → kesin aksesuar
    for url_pat in URL_DEFINITE_ACCESSORY.get(cat, []):
        if url_pat in url_norm:
            return True, f"URL pattern '{url_pat}'"

    # 2. Kategori-spesifik substring pattern'leri
    patterns = ACCESSORY_PATTERNS.get(cat, [])
    for pat in patterns:
        if pat not in text:
            continue
        # Cooler için bağlam kontrolü: "fan" geçen pattern eşleşti, ama
        # title'da gerçek CPU cooler keyword'leri varsa false positive
        if cat == "cooler" and ("fan" in pat or "kontrol" in pat):
            if any(neg in text for neg in COOLER_CONTEXT_NEGATIVE):
                continue  # gerçek cooler, kasa fanı değil
        return True, f"keyword '{pat}'"

    return False, ""


# ─── Self-test ───

if __name__ == "__main__":
    test_cases = [
        # (component_type, name, url, beklenen, açıklama)
        ("case", "Thermaltake The Tower 600 Light-Year Green Kasa Standı", "", True, "kasa standı"),
        ("case", "MSI MAG FORGE M100A Micro ATX Mid Tower", "", False, "gerçek kasa"),
        # Cooler kasa fanı — KRİTİK
        ("cooler", "COUGAR VORTEX VX120 1x120mm ARGB HDB KASA FANI", "cougar-vortex-vx120-kasa-fani.html", True, "kasa fanı"),
        ("cooler", "Thermalright TL-M12QRW ARGB 120 MM Beyaz Kasa Fanı", "", True, "kasa fanı"),
        # Cooler false positive koruması
        ("cooler", "ZALMAN WHITE 12cm 1800RPM ARGB Fan LGA1700/AM5 Uyumlu Hava Soğutmalı CPU Fan", "", False, "gerçek CPU cooler ('hava soğutmalı')"),
        ("cooler", "BITFENIX KUZY ARGB Fan 240mm Dijital Göstergeli Sıvı Soğutucu", "", False, "AIO ('sıvı')"),
        ("cooler", "COOLER MASTER MASTERLIQUID ML120L V2 SICKLEFLOW RGB LED ISLEMCI SIVI SOGUTMA", "", False, "AIO ('cooler' + 'sivi')"),
        ("cooler", "Thermalright Peerless Assassin 120 Air Tower 157mm", "", False, "tower air cooler"),
        ("cooler", "Corsair AMD TR4 H100i Pro Montaj Kiti", "", True, "montaj kiti"),
        # ER tarafından eklenen ürün adı/link mismatch
        ("cooler", "Cougar AQUA Water 120mm", "cougar-vortex-vx120-1x120mm-argb-hdb-kasa-fani.html", True, "URL kasa-fani"),
    ]
    print("=== Accessory Filter Self-Test ===\n")
    fail = 0
    for cat, name, url, expected, desc in test_cases:
        is_acc, reason = is_accessory(retailer_title=name, url=url, component_type=cat)
        ok = "✓" if is_acc == expected else "✗"
        if is_acc != expected:
            fail += 1
        print(f"  {ok} [{cat:8s}] {desc}")
        print(f"      input : {name[:60]}")
        print(f"      result: is_accessory={is_acc}, reason={reason}")
    print(f"\n{'OK' if fail == 0 else f'{fail} FAIL'}")
