
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
    # 1. AM4 Yükseltici (The Upgrader)
    run_scenario("AM4_YUKSELTICI", [
        "Selam, elimde B550 çipsetli AM4 soket bir anakart var. Sistemi yükseltmek istiyorum. Bu anakarta takabileceğim en güçlü oyun işlemcisi nedir?",
        "Tamam, o işlemciyi seçelim. Peki bu işlemciye uygun sıvı soğutucu önerir misin?"
    ])

    # 2. Vatan Otomatik Sistem (The Vague Requester)
    run_scenario("OTOMATIK_SISTEM_45K", [
        "Bana 45.000 TL bütçeyle sadece oyun oynamak için bir sistem topla. Lütfen Vatan Bilgisayar linklerini de ver.",
        "Güzelmiş, ama anakartı ASUS marka bir modelle değiştirebilir miyiz?"
    ])

    # 3. Kırmızı Takım (The AMD Fanboy)
    run_scenario("AMD_FANBOY", [
        "Sadece AMD marka işlemci ve AMD marka ekran kartı kullanacağım bir sistem istiyorum. 25.000 TL bütçem var. Bana 2 seçenek sun."
    ])

    # 4. Güç Kaynağı Testi (The Power Checker)
    run_scenario("GUC_KONTROLU", [
        "Sisteme Ryzen 5 7600 ve RTX 4070 Ti Super takacağım. Elimde 500W güç kaynağı var, sence yeterli olur mu?",
        "Anladım, o zaman bu ikiliye tam yetecek ve biraz da pay bırakacak uygun fiyatlı bir PSU öner."
    ])

    # 5. Hata Avcısı (The Fact Checker)
    run_scenario("HATA_AVCISI", [
        "Intel i5-13400F işlemciye DDR5 RAM ve B450 anakart takabilir miyim?"
    ])

if __name__ == "__main__":
    test_all()
