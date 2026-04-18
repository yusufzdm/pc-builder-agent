import urllib.request
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from database.mongo_client import get_components_collection

def compare_formats():
    print("🔍 GITHUB (YENİ FORK) VS MONGODB (MEVCUT KÜTÜPHANE) FORMAT KARŞILAŞTIRMASI\n")
    
    # 1. GitHub'dan bir örnek alalım
    url = "https://raw.githubusercontent.com/tuckerandrew21/pc-part-dataset/main/data/json/video-card.json"
    try:
        with urllib.request.urlopen(url) as response:
            github_data = json.loads(response.read().decode())
            # İlk RTX 5090'ı bulalım
            github_sample = next(item for item in github_data if "5090" in str(item).upper())
    except Exception as e:
        print(f"GitHub verisi çekilemedi: {e}")
        return

    # 2. Kendi veritabanımızdan bir GPU örneği alalım
    col = get_components_collection()
    db_sample = col.find_one({"component_type": "gpu"})
    
    if not db_sample:
        print("Veritabanında GPU bulunamadı!")
        return

    # 3. Formatları ve Anahtarları (Keys) Ekrana Basalım
    print("=== GITHUB ÖRNEĞİ (Yeni Gelen) ===")
    print(f"İsim: {github_sample.get('name')}")
    print("Anahtarlar (Keys):")
    for key, value in list(github_sample.items())[:15]: # İlk 15'i gösterelim
        val_type = type(value).__name__
        print(f"  - {key}: {value} ({val_type})")
        
    print("\n" + "="*50 + "\n")
    
    print("=== MONGODB ÖRNEĞİ (Bizim Mevcut Sistem) ===")
    print(f"İsim: {db_sample.get('name')}")
    print("Anahtarlar (Keys):")
    for key, value in list(db_sample.items())[:15]:
        if key not in ['_id', 'embedding']: # Bunları kalabalık yapmasın diye gizleyelim
            val_type = type(value).__name__
            print(f"  - {key}: {value} ({val_type})")

if __name__ == "__main__":
    compare_formats()
