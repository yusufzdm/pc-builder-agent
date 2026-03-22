
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from agents.graph_builder import GRAPH

def run_scenario(scenario_name, messages):
    print(f"\n{'='*20} SCENARIO: {scenario_name} {'='*20}")
    config = {"configurable": {"thread_id": f"test-{scenario_name}"}}
    
    state = {
        "messages": [],
        "selected_components": {},
        "target_budget": 0,
        "current_spend": 0,
        "errors": [],
        "retry_count": 0,
        "use_case": "general",
    }

    for user_text in messages:
        print(f"\n👤 Kullanıcı: {user_text}")
        # Send current user message
        state["messages"] = [HumanMessage(content=user_text)]
        
        # Stream the graph execution
        final_msg = ""
        for event in GRAPH.stream(state, config={**config, "recursion_limit": 100}, stream_mode="values"):
            if "messages" in event:
                last = event["messages"][-1]
                if isinstance(last, AIMessage) and last.content:
                    final_msg = last.content
            
            # Update state for next turn persistence
            if "target_budget" in event: state["target_budget"] = event["target_budget"]
            if "selected_components" in event: state["selected_components"].update(event["selected_components"])
            if "current_spend" in event: state["current_spend"] = event["current_spend"]

        print(f"🤖 Asistan: {final_msg}")
    print(f"\n{'='*60}")

def test_all():
    # 1. Adım Adımcı: İşlemci -> Anakart -> RAM
    run_scenario("ADIM_ADIMCI", [
        "Selam, oyun için bir sistem toplayacağız. Önce bana 10.000 TL civarı en iyi işlemciyi bul.",
        "Tamam bu işlemciyi seçelim (Ryzen 7 7800X3D). Şimdi buna uygun, bütçemi yormayacak bir anakart öner.",
        "Harika. Peki bu anakarta DDR4 RAM takabilir miyim?"
    ])

    # 2. Parça Değiştirici: Mevcut sistemde GPU büyütme
    run_scenario("PARCA_DEGISTIRICI", [
        "30k bütçeyle bir oyun sistemi topla.",
        "Çok güzel oldu ama ben bu sistemdeki ekran kartını RTX 4080 ile değiştirmek istiyorum. PSU hala yeterli mi?"
    ])

    # 3. Hata Avcısı: Bilerek yanlış soket
    run_scenario("HATA_AVCISI", [
        "Intel i5-13400F işlemci ve ASUS B550M-A (AMD) anakart almak istiyorum. Bu ikisi birlikte çalışır mı?",
        "Anladım, o zaman bana i5-13400F ile uyumlu en ucuz anakartı bul."
    ])

if __name__ == "__main__":
    test_all()
