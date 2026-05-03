"""
audit_cooler_socket.py
Cooler kayıtlarında socket bilgisi var mı? Hangi field'lar dolu?
"""

import sys
import re
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db

db = get_db()
comp = db["components"]
inv = db["inventory"]

print("=" * 70)
print("[1] components.cooler — hangi field'lar var?")
print("=" * 70)

# İlk 5 cooler kaydının field'larına bak
samples = list(comp.find({"component_type": "cooler"}, {"_id": 0, "embedding": 0}).limit(3))
for s in samples:
    print(f"\n--- {s.get('name', '?')[:60]} ---")
    for k, v in s.items():
        if k == "description_text":
            continue
        v_str = str(v)[:100]
        print(f"  {k:30s}: {v_str}")

print()
print("=" * 70)
print("[2] cooler kayıtlarında socket-related field istatistiği")
print("=" * 70)

socket_fields = ["compatible_sockets", "supported_sockets", "sockets",
                 "cpu_sockets", "socket"]
for f in socket_fields:
    nonnull = comp.count_documents({"component_type": "cooler", f: {"$exists": True, "$ne": None, "$ne": []}})
    print(f"  {f:25s}: {nonnull} kayıtta dolu")

# specifications içine bakıyor mu?
spec_count = comp.count_documents({"component_type": "cooler", "specifications": {"$exists": True, "$ne": None}})
print(f"  specifications (genel) : {spec_count} kayıtta dolu")

# Birkaç sample specification göster
sample = comp.find_one({"component_type": "cooler", "specifications": {"$exists": True}})
if sample and sample.get("specifications"):
    print(f"\n  specifications örneği:")
    spec = sample["specifications"]
    if isinstance(spec, dict):
        for k, v in list(spec.items())[:10]:
            print(f"    {k}: {v}")

print()
print("=" * 70)
print("[3] Cooler isimlerinde socket pattern'i tespit (name-based fallback)")
print("=" * 70)

# Cooler name'lerinde socket pattern
SOCKET_PATTERNS = {
    "AM4":      r"\bam4\b",
    "AM5":      r"\bam5\b",
    "LGA1700":  r"\blga\s*1700\b|\b1700\s*p?\b",
    "LGA1851":  r"\blga\s*1851\b|\b1851\s*p?\b",
    "LGA1200":  r"\blga\s*1200\b|\b1200\b",
    "LGA1151":  r"\blga\s*1151\b|\b1151\b",
    "TR4":      r"\btr4\b",
    "sTRX4":    r"\bstrx4\b",
}

socket_hits = Counter()
total = 0
all_coolers = list(comp.find({"component_type": "cooler"}, {"_id": 0, "name": 1}))
for c in all_coolers:
    name = (c.get("name") or "").lower()
    if not name:
        continue
    total += 1
    for sock, pat in SOCKET_PATTERNS.items():
        if re.search(pat, name):
            socket_hits[sock] += 1

print(f"  Toplam cooler: {total}")
for sock, n in socket_hits.most_common():
    print(f"  {sock:10s}: {n} cooler name'de geçiyor")
print(f"\n  Sadece socket bilgisi olmayan cooler örnekleri:")
no_socket = []
for c in all_coolers[:100]:
    name = (c.get("name") or "").lower()
    has_any = any(re.search(pat, name) for pat in SOCKET_PATTERNS.values())
    if not has_any:
        no_socket.append(c.get("name", "?"))
for n in no_socket[:5]:
    print(f"    - {n[:80]}")

print()
print("=" * 70)
print("[4] AMD Wraith Stealth — örnek 'feedback bug ürün'")
print("=" * 70)

# Bu kayıt feedback'te ortaya çıkan AM4 cooler
wraith = comp.find_one({"name": {"$regex": "Wraith Stealth"}})
if wraith:
    print(f"  Bulundu: {wraith.get('name')}")
    print(f"  Tüm field'ları:")
    for k, v in wraith.items():
        if k in ["embedding", "description_text", "_id"]:
            continue
        v_str = str(v)[:120]
        print(f"    {k:30s}: {v_str}")
