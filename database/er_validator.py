"""
database/er_validator.py
Entity Resolution sonucunda components.name ile inventory.retailer_title/url
arasında kategori-spesifik kritik özellik tutarlılığı kontrolü.

Kullanım:
    from database.er_validator import validate_er_match
    is_valid, reason = validate_er_match(
        components_name=tech_doc["name"],
        retailer_title=item["name"],
        url=item["url"],
        component_type=item["component_type"],
    )
    if not is_valid:
        # bu eşleşme yanlış — DB'ye yazma

Mekanizma kategoriler:
  - memory: DDR tipi (DDR3/DDR4/DDR5) — components vs URL/title farklıysa MISMATCH
  - psu: wattaj — fark > 50W ise MISMATCH
  - storage: PCIe generation (3/4/5) — components vs URL farklıysa MISMATCH

Önceki feedback'lerde tespit edilen bug'lar:
  - "GOODRAM IRDM DDR5" name vs "PC4-25600 DDR4" link
  - "FSP400-60GHS 400W" name vs "FSP SP400-A 350W" link
  - "Samsung PM951 Gen3" name vs "PM9C1B Gen4" link
"""

import re


# ─── Kategori tespit yardımcıları ───

def detect_ddr_type(text: str | None) -> str | None:
    """RAM kayıtlarında DDR tipi tespit. PC4 = DDR4, PC5 = DDR5."""
    if not text:
        return None
    t = text.lower()
    if re.search(r"\bpc5[-\s]?\d", t) or re.search(r"\bddr5\b", t) or "ddr5-" in t:
        return "DDR5"
    if re.search(r"\bpc4[-\s]?\d", t) or re.search(r"\bddr4\b", t) or "ddr4-" in t:
        return "DDR4"
    if re.search(r"\bpc3[-\s]?\d", t) or re.search(r"\bddr3\b", t) or "ddr3-" in t:
        return "DDR3"
    return None


def detect_psu_wattage(text: str | None) -> int | None:
    """PSU kayıtlarında wattaj tespit (200-2000W aralığında)."""
    if not text:
        return None
    # "500W", "500 W", "1000w" gibi pattern'ler
    m = re.search(r"\b(\d{3,4})\s*w\b", text.lower())
    if m:
        try:
            w = int(m.group(1))
            if 200 <= w <= 2000:
                return w
        except ValueError:
            pass
    return None


def detect_pcie_gen(text: str | None) -> int | None:
    """SSD kayıtlarında PCIe generation tespit (3/4/5).
    Sıkı pattern'lar — 'PCIe 5000 MB/s' (hız değeri) gen5 olarak yakalanmamalı.
    Kabul edilen formatlar:
      - 'gen 5', 'gen5'
      - 'pcie 5.0' (sürüm noktası ile)
      - '5.0 x4', '5.0x4' (x4/x8 lane sayısı ile)
      - 'pcie 5x4', 'pcie 5 x4' (lane sayısı ile)
    """
    if not text:
        return None
    t = text.lower()
    # Negative lookahead (?!\d) ile rakam sonrası rakam gelmemeli — "5000" gen5 olarak
    # yakalanmaz ama "gen4x4" / "pcie 4.0" yakalanır.
    if re.search(r"\bgen\s*5(?!\d)", t) or \
       re.search(r"\bpcie\s*5\.0(?!\d)", t) or \
       re.search(r"\b5\.0\s*x\s*\d", t):
        return 5
    if re.search(r"\bgen\s*4(?!\d)", t) or \
       re.search(r"\bpcie\s*4\.0(?!\d)", t) or \
       re.search(r"\b4\.0\s*x\s*\d", t):
        return 4
    if re.search(r"\bgen\s*3(?!\d)", t) or \
       re.search(r"\bpcie\s*3\.0(?!\d)", t) or \
       re.search(r"\b3\.0\s*x\s*\d", t):
        return 3
    return None


# ─── Ana validator ───

def validate_er_match(components_name: str | None = None,
                       retailer_title: str | None = None,
                       url: str | None = None,
                       component_type: str | None = None) -> tuple[bool, str]:
    """
    components.name ile inventory.retailer_title/url eşleşmesini kategori-spesifik
    cross-validate eder.

    Returns:
        (is_valid: bool, reason: str)
        is_valid=True ise eşleşme sağlam (veya bu kategori için kontrol yok).
        is_valid=False ise reason mismatch'i açıklar.

    Tip uyumsuzluğu sadece HER İKİ TARAFTA da tespit edilebildiğinde flag'lenir.
    Tek taraftan tespit edilemediği durumda (eksik veri) match geçerli sayılır
    — false negative riski almaktansa false positive olabilen kayıt geçer.
    """
    cat = (component_type or "").lower()
    title_or_url = " ".join(filter(None, [retailer_title, url]))

    if cat == "memory":
        comp_ddr = detect_ddr_type(components_name)
        ext_ddr = detect_ddr_type(title_or_url)
        if comp_ddr and ext_ddr and comp_ddr != ext_ddr:
            return False, f"DDR tipi mismatch: components.name='{comp_ddr}' vs link='{ext_ddr}'"

    elif cat == "psu":
        comp_w = detect_psu_wattage(components_name)
        ext_w = detect_psu_wattage(title_or_url)
        # Eşik: 50W fark (≥) — aynı modelin küçük varyantları (450W vs 500W) için
        # tolerans bırakmaz; net farklı PSU modelleri (400W vs 350W) yakalanır.
        if comp_w and ext_w and abs(comp_w - ext_w) >= 50:
            return False, f"PSU wattaj mismatch: components.name={comp_w}W vs link={ext_w}W"

    elif cat == "storage":
        comp_gen = detect_pcie_gen(components_name)
        ext_gen = detect_pcie_gen(title_or_url)
        if comp_gen and ext_gen and comp_gen != ext_gen:
            return False, f"PCIe gen mismatch: components.name=Gen{comp_gen} vs link=Gen{ext_gen}"

    return True, ""


# ─── Self-test ───

if __name__ == "__main__":
    cases = [
        # (cat, comp_name, retailer_title, url, beklenen_valid, açıklama)
        ("memory",
         "GOODRAM IRDM Black DDR5-5600 CL30 32GB (2x16GB)",
         "GOODRAM IRDM 3200 MHZ PC4-25600 x Siyah Ram",
         "https://www.mediamarkt.com.tr/tr/product/_goodram-irdm-3200-mhz-pc4-25600-x",
         False, "FEEDBACK BUG — DDR5 name vs DDR4 link"),
        ("memory",
         "Kingston FURY Beast DDR5-5600 CL36 16GB",
         "Kingston FURY Beast DDR5-5600 16GB",
         "https://...",
         True, "DDR5 her iki tarafta — geçerli"),
        ("psu",
         "FSP Group FSP400-60GHS(85)-R SFX 400W Non-Modular 80+ Bronze Certified",
         "FSP Performance SP400-A 350W",
         "https://www.teknosa.com/fsp-performance-sp400-a-350-w-...",
         False, "FEEDBACK BUG — 400W name vs 350W link"),
        ("psu",
         "Enermax MAXPRO ATX 500W",
         "Enermax MAXPRO III 600W",
         "https://...",
         False, "500W vs 600W (>50W fark)"),
        ("storage",
         "Samsung PM951 512GB SSD M.2 PCIe 3.0 NVMe",
         "SAMSUNG PM9C1B 7000/6600MB/s Gen4x4 22x80 NVMe M.2 512 GB SSD",
         "https://www.mediamarkt.com.tr/tr/product/_samsung-pm9c1b-...",
         False, "FEEDBACK BUG — Gen3 name vs Gen4 link"),
        ("storage",
         "WD Blue SN5000 500GB PCIe 4.0 X4 NVMe",
         "WD Blue 500GB SN5000 PCIe Gen4 x4 NVMe",
         "https://...",
         True, "Gen4 her iki tarafta — geçerli"),
        ("cpu",
         "Intel Core i5 12400F",
         "Intel Core i5 12400F",
         "https://...",
         True, "CPU için kontrol yok — default geçerli"),
        ("memory",
         "Lexar THOR DDR4-3200",
         "Lexar Some Other Product",
         "https://...",
         True, "name DDR4, retailer_title DDR'siz — eksik veri, geçerli"),
        # Sıkı pattern testi — false positive olmamalı
        ("storage",
         "WD Blue SN5000 PCIe 4.0 X4 NVMe",
         "WD Blue SN5000 WDS500G4B0E PCIe 5000MB/s Gen4 x4 NVMe",
         "https://...",
         True, "PCIe 5000MB/s hız ifadesi gen5 olarak yakalanmamalı"),
        ("storage",
         "Some SSD PCIe 4.0",
         "Title with Gen 5 mention",
         "https://...",
         False, "Gen 5 (boşluklu) yakalanmalı"),
    ]

    print("=== ER Validator Self-Test ===\n")
    fail = 0
    for cat, comp_name, title, url, exp_valid, desc in cases:
        is_valid, reason = validate_er_match(
            components_name=comp_name, retailer_title=title, url=url,
            component_type=cat,
        )
        ok = "✓" if is_valid == exp_valid else "✗"
        if is_valid != exp_valid:
            fail += 1
        print(f"  {ok} [{cat:8s}] {desc}")
        if not is_valid:
            print(f"      reason: {reason}")
    print(f"\n{'OK' if fail == 0 else f'{fail} FAIL'}")
