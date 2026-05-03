"""
audit_mb_memory_speed.py
Motherboard'larda memory.speed / max_speed / supported_speeds field'ı var mı?
Chipset bazında dağılım nedir?
"""

import sys
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from database.mongo_client import get_db


def main():
    db = get_db()
    comp = db["components"]

    mbs = list(comp.find({"component_type": "motherboard"}, {
        "_id": 0,
        "name": 1,
        "memory": 1,
        "chipset": 1,
        "socket": 1,
    }))

    print(f"Toplam motherboard: {len(mbs)}\n")

    # memory dict içindeki tüm key'leri topla
    key_counts = Counter()
    examples = {}
    for m in mbs:
        mem = m.get("memory")
        if isinstance(mem, dict):
            for k in mem.keys():
                key_counts[k] += 1
                if k not in examples:
                    examples[k] = mem[k]

    print("=== motherboard.memory içindeki field'lar ===")
    for k, c in key_counts.most_common():
        print(f"  {k:20s}: {c:4d} kayıtta var, örnek: {examples[k]!r}")

    # Chipset dağılımı
    chipset_counts = Counter()
    chipset_speeds = defaultdict(list)
    for m in mbs:
        chipset = m.get("chipset") or "?"
        chipset_counts[chipset] += 1
        mem = m.get("memory") or {}
        speed = mem.get("speed") or mem.get("max_speed") or mem.get("supported_speeds")
        if speed:
            chipset_speeds[chipset].append(speed)

    print("\n=== Chipset dağılımı (top 20) ===")
    for chip, c in chipset_counts.most_common(20):
        speeds = chipset_speeds.get(chip, [])
        unique = list(set(map(str, speeds))) if speeds else []
        print(f"  {chip:20s}: {c:4d} kayıt, hızlar: {unique[:5]}")

    # Birkaç sample motherboard'ın tam memory dict'ini göster
    print("\n=== 5 SAMPLE MOTHERBOARD MEMORY ===")
    for m in mbs[:5]:
        print(f"\n  {m.get('name', '?')[:70]}")
        print(f"    chipset: {m.get('chipset')}, socket: {m.get('socket')}")
        print(f"    memory:  {m.get('memory')!r}")


if __name__ == "__main__":
    main()
