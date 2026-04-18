"""
main.py
PC Builder Agent Faz 1 — Giriş Noktası
LangGraph akışını başlatır, kullanıcı ile terminal üzerinden konuşma yürütür.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

# API anahtarlarını kontrol et
if not os.getenv("OPENAI_API_KEY"):
    print("❌ HATA: .env dosyasında OPENAI_API_KEY bulunamadı!")
    sys.exit(1)
if not os.getenv("MONGO_URI"):
    print("❌ HATA: .env dosyasında MONGO_URI bulunamadı!")
    sys.exit(1)

# Grafı yükle
from agents.graph_builder import GRAPH


def extract_info_from_messages(messages: list) -> dict:
    """İlk mesajdan bütçe ve kullanım amacı ipucu çıkarmaya çalışır."""
    if not messages:
        return {}
    text = messages[0].content if hasattr(messages[0], "content") else str(messages[0])
    import re
    
    info = {"target_budget": 0, "use_case": "general"}
    
    # Bütçe: "30000 TL", "30k", "30 bin"
    match = re.search(r"(\d[\d.]*)\s*(TL|tl|k\b|bin)", text, re.IGNORECASE)
    if match:
        val_str = match.group(1).replace(".", "")
        try:
            val = float(val_str)
            if "k" in match.group(2).lower() or "bin" in match.group(2).lower():
                val *= 1000
            info["target_budget"] = int(val)
        except ValueError:
            pass
            
    # Kullanım Amacı
    use_case_map = {
        'oyun': 'gaming', 'game': 'gaming', 'gaming': 'gaming',
        'mimarlık': 'architecture', 'mimarlik': 'architecture', 'çizim': 'architecture',
        'render': 'rendering', 'video': 'rendering', 'kurgu': 'rendering',
        'ofis': 'office', 'iş': 'office', 'ders': 'office',
        'genel': 'general'
    }
    for keyword, mapped in use_case_map.items():
        if keyword in text.lower():
            info["use_case"] = mapped
            break
            
    return info


def run():
    print("\n" + "=" * 55)
    print("🖥️  PC TOPLAMA ASISTANI (Faz 2 — LangGraph + MongoDB)")
    print("   Çıkmak için 'q' veya 'çık' yaz.")
    print("=" * 55 + "\n")

    config = {"configurable": {"thread_id": "session-01"}}
    initial_state = {
        "selected_components": {},
        "target_budget": 0,
        "current_spend": 0,
        "errors": [],
        "retry_count": 0,
        "use_case": "general",
    }

    while True:
        try:
            user_input = input("Siz: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["q", "exit", "çık", "quit"]:
                print("👋 Görüşmek üzere!")
                break

            # İlk mesajdan bütçe ve kullanım amacı çıkar
            extracted = extract_info_from_messages([HumanMessage(content=user_input)])
            if extracted.get("target_budget", 0) > 0 and initial_state["target_budget"] == 0:
                initial_state["target_budget"] = extracted["target_budget"]
                print(f"  💰 Bütçe algılandı: {initial_state['target_budget']:,} TL")
            if extracted.get("use_case") != "general" and initial_state["use_case"] == "general":
                initial_state["use_case"] = extracted["use_case"]
                print(f"  📂 Kullanım amacı: {initial_state['use_case']}")

            # Grafiği çalıştır
            last_printed_id = None
            for event in GRAPH.stream(
                {**initial_state, "messages": [HumanMessage(content=user_input)]},
                config={**config, "recursion_limit": 50},
                stream_mode="values",
            ):
                if "messages" in event:
                    last = event["messages"][-1]
                    # Sadece yeni AI mesajlarını yazdır (ID ile tekrar önle)
                    if isinstance(last, AIMessage) and last.content:
                        msg_id = getattr(last, "id", None) or last.content[:30]
                        if msg_id != last_printed_id:
                            last_printed_id = msg_id
                            print(f"\n🤖 Asistan: {last.content}\n")


                # State'i güncelle
                if "target_budget" in event and event["target_budget"] > 0:
                    initial_state["target_budget"] = event["target_budget"]
                if "current_spend" in event:
                    initial_state["current_spend"] = event["current_spend"]
                if "selected_components" in event and event["selected_components"]:
                    initial_state["selected_components"].update(event["selected_components"])
                if "use_case" in event:
                    initial_state["use_case"] = event["use_case"]

                # Validator uyarılarını göster
                if "errors" in event and event["errors"]:
                    for err in event["errors"]:
                        if err not in initial_state.get("_shown_errors", set()):
                            print(f"  {err}")
                            initial_state.setdefault("_shown_errors", set()).add(err)

        except KeyboardInterrupt:
            print("\n\n👋 Ctrl+C ile çıkıldı.")
            break
        except Exception as e:
            print(f"⚠️  Hata: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    run()
