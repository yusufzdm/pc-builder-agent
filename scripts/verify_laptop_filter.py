"""
verify_laptop_filter.py
Laptop filter düzgün çalışıyor mu — doğrulama testi.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.logic_engine import PCBuilderLogic
from database.mongo_client import get_db

logic = PCBuilderLogic()

print("=" * 60)
print("LAPTOP FILTER DOĞRULAMA")
print("=" * 60)

print("\n[1] DDR5 RAM seçim testi (H610 chipset, cap=4800)")
result = logic._select_best_ram("DDR5", 15000, max_speed=4800)
if result:
    name = result.get("name", "?")
    ff = result.get("form_factor", "?")
    price = result.get("price", 0)
    is_sodimm = "sodimm" in (ff or "").lower().replace("-", "")
    print(f"  Seçim     : {name}")
    print(f"  Form fact.: {ff}")
    print(f"  Fiyat     : {price:,} TL")
    print(f"  SODIMM mi?: {is_sodimm}  {'❌ HALA SORUN' if is_sodimm else '✓ DESKTOP UDIMM'}")
else:
    print("  Sonuç yok")

print("\n[2] DDR5 RAM ucuz arama (cap yok)")
result2 = logic._select_best_ram("DDR5", 10000)
if result2:
    name = result2.get("name", "?")
    ff = result2.get("form_factor", "?")
    is_sodimm = "sodimm" in (ff or "").lower().replace("-", "")
    print(f"  Seçim     : {name}")
    print(f"  Form fact.: {ff}")
    print(f"  SODIMM mi?: {is_sodimm}  {'❌' if is_sodimm else '✓'}")

print("\n[3] DB'de KVR48S40BS8 (laptop SODIMM) durumu")
db = get_db()
doc = db["inventory"].find_one({"retailer_title": {"$regex": "KVR48S40BS8"}})
if doc:
    print(f"  Kayıt    : {doc.get('retailer_title')}")
    print(f"  is_laptop: {doc.get('is_laptop')}  (True ise search onu filtreliyor)")
    print(f"  Beklenen : True (flag set, search gizliyor)")
else:
    print("  KVR48S40BS8 inventory'de bulunamadı")

print("\n[4] DB'de mSATA SSD durumu")
doc = db["inventory"].find_one({"retailer_title": {"$regex": "mSATA"}})
if doc:
    print(f"  Kayıt    : {doc.get('retailer_title')}")
    print(f"  is_laptop: {doc.get('is_laptop')}")

print("\n[5] _query_inventory('memory') — SODIMM çıkıyor mu?")
result3 = logic._query_inventory("memory", max_price=15000, filters={"ram_type": "DDR5"})
if result3:
    name = result3.get("name", "?")
    ff = result3.get("form_factor", "?")
    is_sodimm = "sodimm" in (ff or "").lower().replace("-", "")
    print(f"  Seçim     : {name}")
    print(f"  Form fact.: {ff}")
    print(f"  SODIMM mi?: {is_sodimm}  {'❌' if is_sodimm else '✓'}")

print("\n[6] _query_inventory('storage') — mSATA çıkıyor mu?")
result4 = logic._query_inventory("storage", max_price=10000)
if result4:
    name = result4.get("name", "?")
    ff = result4.get("form_factor", "?")
    is_msata = "msata" in (ff or "").lower() or "msata" in name.lower()
    print(f"  Seçim     : {name}")
    print(f"  Form fact.: {ff}")
    print(f"  mSATA mi? : {is_msata}  {'❌' if is_msata else '✓'}")
