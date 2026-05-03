"""
verify_use_case_extract.py
extract_info_from_messages doğru use_case çıkarıyor mu?
Önceki bug: "tasarım işleri" → "iş" partial match → office (yanlış).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from langchain_core.messages import HumanMessage
from main import extract_info_from_messages

cases = [
    # (input, beklenen_use_case, beklenen_butce, açıklama)
    ("55 k ya tasarım işleri için kullanacağım bi bilgisayar ver", "design", 55000, "FEEDBACK BUG — tasarım işleri 'iş' partial match"),
    ("Photoshop ve Illustrator için 60K bütçeyle pc öner", "design", 60000, "design (photoshop)"),
    ("Figma ile UI tasarımı yapacağım, 40K", "design", 40000, "design (figma)"),
    ("Premiere ve After Effects için 100K", "rendering", 100000, "rendering (video kurgu)"),
    ("Blender ile 3D render, 80 bin", "rendering", 80000, "rendering (blender)"),
    ("video kurgu yapacağım 70k", "rendering", 70000, "rendering (video kurgu phrase)"),
    ("oyun için 50000 TL", "gaming", 50000, "gaming"),
    ("oyunlar için pc istiyorum 45k", "gaming", 45000, "gaming (oyunlar)"),
    ("AutoCAD ve Revit için 90K bütçe", "architecture", 90000, "architecture (autocad)"),
    ("Mimarlık ofisinde kullanacağım 60K", "architecture", 60000, "architecture > office (öncelik)"),
    ("ofis için 20K", "office", 20000, "office (ofis)"),
    ("iş yerinde kullanacağım 25K", "office", 25000, "office (iş yeri phrase)"),
    ("muhasebe için 18K", "office", 18000, "office (muhasebe)"),
    ("ders için 15K", "office", 15000, "office (ders)"),
    ("genel kullanım 30K", "general", 30000, "general"),
    # Edge case'ler
    ("İşim yoğun, hızlı bir bilgisayar lazım", "general", 0, "iş partial — match yok, default general"),
    ("değişiklik yapmam gerekiyor 50K", "general", 50000, "değişiklik 'iş' içeriyor ama match olmamalı"),
]

print("=== Use Case Extract Doğrulama ===\n")
fail = 0
for text, exp_uc, exp_budget, desc in cases:
    info = extract_info_from_messages([HumanMessage(content=text)])
    actual_uc = info.get("use_case")
    actual_budget = info.get("target_budget", 0)
    ok_uc = actual_uc == exp_uc
    ok_budget = actual_budget == exp_budget
    status = "✓" if ok_uc and ok_budget else "✗"
    if not (ok_uc and ok_budget):
        fail += 1
    print(f"  {status} {desc}")
    print(f"      input : {text[:65]}")
    print(f"      use_case: {actual_uc}  (beklenen: {exp_uc})  budget: {actual_budget:,}  (beklenen: {exp_budget:,})")

print(f"\n{'OK' if fail == 0 else f'{fail} FAIL'}")
