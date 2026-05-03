"""
test_design_scenario.py
Feedback'teki "55K tasarım işleri" senaryosunu agent ile çalıştır,
artık doğru use_case (design) ile build üretildiğini doğrula.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.logic_engine import PCBuilderLogic, ValidatorNode

logic = PCBuilderLogic()
validator = ValidatorNode()

print("=" * 70)
print("DESIGN_55K — '55 k ya tasarım işleri için kullanacağım bi bilgisayar ver'")
print("=" * 70)

build = logic.optimize_build(55000, "design")
parts = build.get("selected_components", {})

for cat, p in parts.items():
    if isinstance(p, dict):
        print(f"  [{cat:12s}] {p.get('name', '?')[:60]:60s} {p.get('price', 0):>8,} TL")

print(f"\n  TOPLAM: {build.get('total_spend', 0):,} TL  /  hedef 55,000 TL")
print(f"  Platform: {build.get('platform', '?')}")

# Validator
v_result = validator({"selected_components": parts, "target_budget": 55000, "use_case": "design"})
print(f"\n  Validator bulguları:")
for err in v_result.get("errors", []):
    print(f"    {err}")

print()
print("=" * 70)
print("KARŞILAŞTIRMA — aynı bütçe office olsaydı (eski bug):")
print("=" * 70)
build_office = logic.optimize_build(55000, "office")
office_parts = build_office.get("selected_components", {})
for cat, p in office_parts.items():
    if isinstance(p, dict):
        print(f"  [{cat:12s}] {p.get('name', '?')[:60]:60s} {p.get('price', 0):>8,} TL")
print(f"\n  TOPLAM: {build_office.get('total_spend', 0):,} TL")
