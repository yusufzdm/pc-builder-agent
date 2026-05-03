"""
database/laptop_filter.py
Bir bileşenin laptop için olup olmadığını tespit eden merkezi helper.

Kullanım:
    from database.laptop_filter import is_laptop_component
    is_lap, reason = is_laptop_component(name, retailer_title, component_type)
    if is_lap:
        # bu kayıt masaüstü build'de kullanılamaz

Hem mevcut DB temizliği için (scripts/cleanup_laptop_components.py) hem de
yeni scrape'lerde (vatan/teknosa/mediamarkt scraper'ları) inventory'e
yazılmadan önce filtre olarak kullanılır.
"""

import re

# ─── Kategori-bağımsız laptop keyword'leri ───
GLOBAL_LAPTOP_KEYWORDS = [
    "laptop", "notebook", "dizüstü", "dizustu",
]

# ─── RAM (memory) — SODIMM tespiti ───
SODIMM_KEYWORDS = [
    "sodimm", "so-dimm", "so dimm",
    "262-pin", "260-pin", "204-pin",  # SODIMM pin sayıları
    "laptop memory", "notebook memory", "laptop ram", "notebook ram",
]
# Kingston ValueRAM: KVR48**S**40BS8-16 ("S" = SODIMM, "U" = UDIMM)
# Crucial: CT16G48C40**S**5 (S = SODIMM)
# ADATA: AD4S/AD5S = SODIMM
# Corsair Vengeance: CMSO/CMSX = SODIMM
# Kingston Fury Impact: KF**X**...IBK (Impact = laptop)
SODIMM_PART_NUMBER_PATTERNS = [
    r"\bKVR\d+S\d+",
    r"\bKCP\d+S",
    r"\bCT\d+G\d+C\d+S\d+",
    r"\bAD\dS\d+",
    r"\bCMSO\d+",
    r"\bCMSX\d+",
    r"\bKF\d+S\d+",
    r"\bKF\d+\w+IBK",
    r"\bM471A\d+",         # Samsung SODIMM
    r"\bHMA\d+S\d+",       # Hynix SODIMM
]

# ─── CPU — laptop suffix ───
# Intel laptop: U/H/HX/HS/P (12. nesil+), Y/M (eski)
# Intel masaüstü: K/KF/F/T/X/(çıplak)
# AMD laptop: U/HS/HX/H (Ryzen 7 7840HS)
# AMD masaüstü: X/X3D/G/GE/F/(çıplak)
# Karışıklık: H/HX hem masaüstü Threadripper hem laptop'ta var → ekstra kontrol
LAPTOP_CPU_PATTERNS = [
    # Intel — 4-5 haneli + U/HX/HS/H/Y/M (kesin laptop suffix)
    r"\bi[3579]-\d{4,5}(U|HX|HS|H[QU]?|Y|M[QX]?)\b",
    r"\bcore\s+i[3579]\s+\d{4,5}(U|HX|HS|H[QU]?|Y|M[QX]?)\b",
    # P suffix — sadece 12. gen+ laptop (Alder Lake-P, Raptor Lake-P).
    # Eski 4-7. gen "P" (örn i5-6402P) low-power MASAÜSTÜ (LGA1151), pattern dışı.
    r"\bi[3579]-1[2-9]\d{3}P\b",
    r"\bcore\s+i[3579]\s+1[2-9]\d{3}P\b",
    # AMD Ryzen mobile — sayıdan sonra U/HS/HX/H
    r"\bryzen\s+[3579]\s+\d{4}(U|HS|HX|H)\b",
    r"\bryzen\s+[3579]\s+(pro\s+)?\d{4}(U|HS|HX|H)\b",
    # AMD Athlon mobile
    r"\bathlon\s+\w*mobile\b",
    # Intel Core Ultra mobile (Meteor Lake/Arrow Lake-H)
    r"\bcore\s+ultra\s+[579]\s+\d{3}H\b",
]

# ─── GPU — Mobile / Max-Q / M-suffix ───
LAPTOP_GPU_PATTERNS = [
    r"\bmobile\b",
    r"\bmax-?q\b",
    r"\bmxm\b",                                  # MXM module = laptop GPU
    # NVIDIA M serisi: GeForce GTX 1060M, RTX 3060M (legacy mobile)
    r"\b(gtx|rtx)\s*\d{3,4}m\b",
    r"\bgeforce\s+\w+\s+\d{3,4}m\b",
    # Quadro Mobile P2000M / T1000M
    r"\bquadro\s+\w+\d+m\b",
]

# ─── Storage — laptop-specific form factors ───
# M.2-2230 / 2242 / 2260 = ağırlıkla laptop için (masaüstüde 2280 standart)
# mSATA = laptop (modern masaüstü anakart yok)
# Strict değil — DB'de masaüstü için 2230 SSD'ler de var, ama büyük ihtimalle laptop
LAPTOP_STORAGE_PATTERNS = [
    r"\bmsata\b",
    # 2.5" not laptop-spesifik (masaüstü SATA SSD'ler de 2.5")
]


def _normalize(text: str) -> str:
    """Pattern matching için lower + extra whitespace temizle."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower()).strip()


def is_laptop_component(name: str | None = None,
                       retailer_title: str | None = None,
                       component_type: str | None = None,
                       form_factor: str | None = None) -> tuple[bool, str]:
    """
    Bir kaydın laptop bileşeni olup olmadığını tespit eder.

    Returns:
        (is_laptop: bool, reason: str) — reason laptop sebebini açıklar.
        is_laptop=False ise reason="".

    component_type opsiyonel ama daha doğru tespit için verilmeli:
        "memory", "cpu", "gpu", "storage" — kategori-spesifik pattern'ler aktive olur.
    """
    text = _normalize(" ".join(filter(None, [name, retailer_title])))
    if not text:
        return False, ""

    # 1. Global keyword'ler — her kategori için
    for kw in GLOBAL_LAPTOP_KEYWORDS:
        if kw in text:
            return True, f"keyword '{kw}'"

    cat = (component_type or "").lower()

    # 2. Memory (RAM) — SODIMM tespiti
    if cat == "memory":
        for kw in SODIMM_KEYWORDS:
            if kw in text:
                return True, f"SODIMM keyword '{kw}'"
        for pat in SODIMM_PART_NUMBER_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True, f"SODIMM part-number pattern '{pat}'"
        # form_factor doğrulaması (verilmişse)
        ff = (form_factor or "").lower().replace(" ", "").replace("-", "")
        if "sodimm" in ff:
            return True, f"form_factor '{form_factor}'"

    # 3. CPU — mobile suffix tespiti
    elif cat == "cpu":
        for pat in LAPTOP_CPU_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True, f"laptop CPU pattern '{pat}'"

    # 4. GPU — Mobile / Max-Q / M-suffix
    elif cat == "gpu":
        for pat in LAPTOP_GPU_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True, f"mobile GPU pattern '{pat}'"

    # 5. Storage — mSATA gibi laptop-only formatlar
    elif cat == "storage":
        for pat in LAPTOP_STORAGE_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True, f"laptop storage pattern '{pat}'"

    return False, ""


# ─── Self-test (manuel debug için) ───

if __name__ == "__main__":
    test_cases = [
        # (component_type, name/title, beklenen)
        ("memory", "Kingston ValueRAM KVR48S40BS8-16 16 GB DDR5 4800 MHz CL40", True),
        ("memory", "Kingston ValueRAM KVR48U40BS8-16 16 GB DDR5 4800 MHz CL40", False),
        ("memory", "TEAMGROUP T-Force Vulcan DDR5-6000 CL38 16GB (1x16GB)", False),
        ("memory", "Crucial CT16G48C40S5 16GB DDR5-4800 SODIMM Laptop Memory", True),
        ("cpu", "Intel Core i5 12400F 2.5 GHz 6-Core LGA1700", False),
        ("cpu", "Intel Core i7-13700H 2.4 GHz 14-Core Mobile", True),
        ("cpu", "AMD Ryzen 7 7840HS 8-Core Mobile Processor", True),
        ("cpu", "AMD Ryzen 7 7700X 8-Core AM5", False),
        ("cpu", "Intel Core i5 6402P 2.8 GHz 4-Core LGA1151", False),  # eski LP masaüstü
        ("cpu", "Intel Core i7-13720P 5.0 GHz 12-Core Mobile", True),   # 12+ gen P = laptop
        ("gpu", "Asus TUF GAMING Radeon RX 7800 XT 16GB", False),
        ("gpu", "NVIDIA GeForce RTX 3070 Mobile Max-Q 8GB", True),
        ("gpu", "GeForce GTX 1060 6GB Notebook", True),
        ("storage", "Samsung 980 PRO 1TB M.2-2280 NVMe", False),
        ("storage", "Crucial M500 240GB mSATA SSD", True),
        ("case", "Thermaltake The Tower 600 ATX Mid Tower", False),
        ("case", "MSI Stealth 16 Laptop Cover", True),  # global keyword
    ]
    print("=== Laptop Filter Self-Test ===\n")
    fail = 0
    for cat, name, expected in test_cases:
        is_lap, reason = is_laptop_component(name=name, component_type=cat)
        ok = "✓" if is_lap == expected else "✗"
        if is_lap != expected:
            fail += 1
        print(f"  {ok} [{cat:8s}] {name[:55]:55s} -> {is_lap} ({reason})")
    print(f"\n{'OK' if fail == 0 else f'{fail} FAIL'}")
