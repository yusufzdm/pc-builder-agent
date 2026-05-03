"""
Vatan ve Teknosa GPU listelerini karsilastirir.

Yontem:
  - name'i normalize et (lowercase, noktalama -> bosluk, gurultu kelimeleri at)
  - chip ailesi (rtx/gtx/rx/arc + model no), AIB markasi (asus/msi/gigabyte/...) ve bellek (8gb/12gb/16gb...)
    parmak izini cikar
  - Iki taraf arasinda Jaccard token-set benzerligi >= 0.7 ise "ayni" say
  - Detayli raporu konsola bas
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
VATAN = ROOT / "scrapers" / "data" / "vatan" / "scrape_gpu.json"
TEKNOSA = ROOT / "scrapers" / "data" / "teknosa" / "new_items_gpu.json"

# Karsilastirmada anlam tasimayan kelimeler
NOISE = {
    "ekran", "karti", "kartı", "graphics", "card", "gpu", "video",
    "aksesuarsiz", "aksesuarsız", "yeni", "kutu",
    "bit", "bitlik", "bus",
    "with", "and", "ve", "the", "for",
    "dlss", "ray", "tracing", "rt",
}

GB_RE = re.compile(r"(\d+)\s*gb")
BIT_RE = re.compile(r"(\d+)\s*bit")
MODEL_RE = re.compile(r"\b(rtx|gtx|rx|arc)\s*([a-z]?\d{3,4}\s*[a-z]{0,3})", re.I)

AIB_BRANDS = {
    "asus", "msi", "gigabyte", "palit", "zotac", "inno3d", "pny",
    "sapphire", "powercolor", "xfx", "evga", "colorful", "galax",
    "gainward", "kfa2", "asrock", "amd", "nvidia", "intel",
}


def normalize(name: str) -> str:
    n = name.lower()
    n = re.sub(r"[^a-z0-9\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def fingerprint(name: str) -> dict:
    n = normalize(name)
    tokens = [t for t in n.split() if t not in NOISE]

    chip = None
    m = MODEL_RE.search(n)
    if m:
        chip_family = m.group(1).lower()
        chip_model = re.sub(r"\s+", "", m.group(2).lower())
        chip = f"{chip_family}{chip_model}"

    mem = None
    g = GB_RE.search(n)
    if g:
        mem = f"{g.group(1)}gb"

    aib = None
    for t in tokens:
        if t in AIB_BRANDS:
            aib = t
            break

    return {
        "raw": name,
        "norm": n,
        "tokens": set(tokens),
        "chip": chip,
        "mem": mem,
        "aib": aib,
        "key": (aib, chip, mem),
    }


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def series_tokens(fp: dict) -> set:
    """Bir GPU'nun AIB seri/alt-model tokenlarini cikarir (chip ve bellek haric)."""
    drop = NOISE | AIB_BRANDS | {"geforce", "radeon", "nvidia", "amd", "intel",
                                  "rtx", "gtx", "rx", "arc", "gddr", "gddr6", "gddr7",
                                  "gddr5", "gddr3", "ddr3", "ddr5",
                                  "pcie", "pci", "express", "hdmi", "dp", "vga", "dvi",
                                  "x8", "x16", "x4", "lp", "low", "profile",
                                  "dx11", "dx12", "fsr", "rdna", "fan",
                                  "oyuncu", "gaming", "vga"}
    out = set()
    for t in fp["tokens"]:
        if t in drop:
            continue
        if GB_RE.fullmatch(t) or BIT_RE.fullmatch(t):
            continue
        if t.isdigit():
            continue
        # chip token'larini at (rtx5060, rx9070, vb. fingerprint icinde zaten var)
        if fp["chip"] and t in fp["chip"]:
            continue
        # tek harfli artiklar / sasi ekleri
        if len(t) <= 1:
            continue
        out.add(t)
    return out


def main():
    vatan = [fingerprint(r["name"]) for r in json.load(open(VATAN, encoding="utf-8"))]
    teknosa = [fingerprint(r["name"]) for r in json.load(open(TEKNOSA, encoding="utf-8"))]

    for fp in vatan + teknosa:
        fp["series"] = series_tokens(fp)

    print(f"Vatan GPU adedi   : {len(vatan)}")
    print(f"Teknosa GPU adedi : {len(teknosa)}")

    matched_pairs = []
    used_v = set()
    used_t = set()

    # Tum vatan-teknosa ciftleri arasinda en iyi eslesmeyi greedy bul
    candidates = []
    for v in vatan:
        for t in teknosa:
            if not (v["aib"] and t["aib"] and v["aib"] == t["aib"]):
                continue
            if not (v["chip"] and t["chip"] and v["chip"] == t["chip"]):
                continue
            if not (v["mem"] and t["mem"] and v["mem"] == t["mem"]):
                continue
            # Seri tokeni kesismeli ya da iki tarafta da hic seri tokeni olmamali
            sv, st = v["series"], t["series"]
            if sv and st:
                inter = sv & st
                if not inter:
                    continue
                score = len(inter) / max(len(sv | st), 1)
            else:
                # ikisi de generic (Asrock RX 9070 XT Challenger ile generic eslesirse low score)
                score = 0.5
            candidates.append((score, v, t))

    candidates.sort(key=lambda x: -x[0])
    for score, v, t in candidates:
        if id(v) in used_v or id(t) in used_t:
            continue
        used_v.add(id(v))
        used_t.add(id(t))
        matched_pairs.append((v, t, score, "key+series"))

    matched_v_ids = {id(v) for v, _, _, _ in matched_pairs}
    matched_t_ids = {id(t) for _, t, _, _ in matched_pairs}

    only_vatan = [fp for fp in vatan if id(fp) not in matched_v_ids]
    only_teknosa = [fp for fp in teknosa if id(fp) not in matched_t_ids]

    print()
    print("=" * 70)
    print(f"  Eslesen (ayni urun)         : {len(matched_pairs)}")
    print(f"    -> kesin anahtar (aib+chip+mem) : {sum(1 for _,_,_,s in matched_pairs if s=='key')}")
    print(f"    -> token bazli fuzzy >= 0.7     : {sum(1 for _,_,_,s in matched_pairs if s=='fuzzy')}")
    print(f"  Sadece Vatan'da             : {len(only_vatan)}")
    print(f"  Sadece Teknosa'da           : {len(only_teknosa)}")
    print("=" * 70)

    print("\n--- Eslesen ilk 15 ornek ---")
    for v, t, s, src in matched_pairs[:15]:
        print(f"  [{src} {s:.2f}]")
        print(f"    V: {v['raw']}")
        print(f"    T: {t['raw']}")

    print("\n--- Sadece Vatan (ilk 15) ---")
    for fp in only_vatan[:15]:
        print(f"  - {fp['raw']}")

    print("\n--- Sadece Teknosa (ilk 15) ---")
    for fp in only_teknosa[:15]:
        print(f"  - {fp['raw']}")


if __name__ == "__main__":
    main()
