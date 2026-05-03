"""
agents/graph_builder.py
PC Builder Agent - LangGraph Orkestrasyonu (Stabil Versiyon)
"""

import os
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import tools_condition

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.logic_engine import ValidatorNode
from agents.tools import ALL_TOOLS

load_dotenv()

# --- State Tanımı ---
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    target_budget: int
    current_spend: int
    selected_components: dict
    errors: list
    retry_count: int
    use_case: str

# --- Sistem Prompt ---
SYSTEM_PROMPT = """SEN UZMAN BİR PC TOPLAMA ASİSTANISIN.

⛔ TEMEL KURALLAR:
1. **HEMEN ARA:** Kullanıcı bütçe ve kullanım amacı belirttiğinde HEMEN `optimize_build` aracını çağır. Soru sorma, doğrudan sistemi topla.
2. **TEKNİK UYUM:** Anakart ararken işlemcinin soketine ve RAM tipine (DDR4/DDR5) dikkat et. AM5 soket CPU ile AM4 anakart KULLANILAMAZ.
3. **PARÇA PARÇA ARAMA:** Kullanıcı tek bir parça istediğinde ilgili `search_*` aracını BİR KEZ çağır.
4. **STOK DIŞI:** Kullanıcı "stok önemli değil" derse `search_reference_library` kullan.
5. **LİNKLERİ PAYLAŞ:** Sonuçlarda 'url' varsa `[retailer_title](url)` formatında link ver. 'retailer_title' perakendecideki gerçek ürün adıdır ve URL ile eşleşir.
   **ÇOKLU PERAKENDECİ KARŞILAŞTIRMA:** `optimize_build` aracı sonucu "=== HAZIR BUILD ÖZETİ ===" bloğu içerir — bu bloğu **BİREBİR KOPYALA**, JSON_DATA kısmını ATLA, kendi başlık/açıklama EKLEME. Sadece ürün listesi sonrasında "Onaylıyor musunuz?" yazabilirsin. Search araçlarında `retailer_comparison` field'ı varsa o satırı birebir kullan.
6. **GÜNCEL DONANIM:** DDR3 veya eski nesil parçalar önerme. Gaming PC için minimum DDR4-3200, tercihen DDR5 kullan.
7. **EKSİKSİZ SİSTEM:** Gaming PC'de mutlaka CPU, GPU, Anakart, RAM, SSD, PSU, Kasa olmalı. GPU'suz gaming PC olmaz (CPU iGPU'lu değilse). Sadece office/general'da iGPU'lu CPU varsa GPU atlanabilir.
8. **RAM KAPASİTESİ KESİN:** RAM toplam kapasitesi için SADECE tool çıktısındaki `capacity` (GB toplam) ve `modules.quantity` × `modules.capacity_gb` değerlerini kullan. Ürün adında "(1x8 GB)" yazıyorsa toplam 8 GB'dır — "4x8 GB" veya "32 GB" gibi UYDURMA. Tek modülse mutlaka "1x8 GB tek modül (single-channel)" diye belirt.
9. **VALIDATÖR HATALARI:** Her parça seçiminden sonra ⛔ hatası varsa O PARÇAYI ALTERNATİFLE DEĞİŞTİR (yeni search çağır), seçimi son kullanıcıya hata ile sunma. Sadece ⚠️ veya 💡 uyarıları toleranslı sunulabilir, ama önce alternatif denemiş olmalısın.
10. **KULLANICI KISITLAMALARI ZORUNLU:** Kullanıcı marka/teknik kısıt belirttiyse (örn "sadece AMD", "Asus marka", "DDR5 olsun", "Vatan'dan al", "RGB'siz") bu HER parça seçiminde uygulanmalı. Aramaları bu kısıtlara göre yap, çıkan sonuçları filtrele. Kullanıcının "sadece AMD" dediği bir senaryoda NVIDIA GPU vermek YASAKTIR — kısıtı ihlal eden parça çıktıysa o aramayı yeniden yap.
11. **HALÜSİNASYON YASAĞI:** Uyumluluk soruları (örn "X CPU + Y RAM uyumlu mu?", "soket tipi nedir?", "TDP ne kadar?") için DAİMA `check_compatibility` veya `search_*` araçlarını çağır. Kendi bilgine güvenip cevap verme — özellikle CPU soketleri (i5-13400F LGA1700'dür, i5-13500 LGA1700'dür, vs.) ve GPU TDP'leri (gen değişiyor, hatırlama). Tool çıktısı yoksa "araştırmam gerek" de.

📋 ONAY AKIŞI:
- Sistem önerisini SUNduktan sonra kullanıcıdan onay iste.
- Kullanıcı "onaylıyorum", "tamam", "evet", "olur" gibi bir şey derse → ONAY ALINMIŞTIR. Tekrar sormak YASAK.
- Onaydan sonra `generate_final_report` aracıyla özet tabloyu oluştur ve satın alma linklerini paylaş.
- "Tamamla" denildiğinde de aynısını yap: final rapor + linkler.
- Aynı listeyi iki kez gösterme.

🚫 YAPMAMAN GEREKENLER:
- "Siparişiniz tamamlandı" veya "bileşenler size ulaşacak" gibi sahte sipariş tamamlama mesajları VERME. Sipariş yeteneğin YOK.
- Kullanıcıya onay verdikten sonra tekrar aynı soruyu sorma.
- Arama sonuçlarında olmayan ürün önerme (halüsinasyon).

Tüm yanıtlarını Türkçe ver.
"""

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
llm_with_tools = llm.bind_tools(ALL_TOOLS)

# --- Düğümler ---
class BudgetAwareToolNode:
    def __init__(self, tools: list):
        self.tools_by_name = {tool.name: tool for tool in tools}

    def __call__(self, state: AgentState) -> dict:
        last_msg = state["messages"][-1]
        new_messages = []
        new_selected = {}
        
        for call in last_msg.tool_calls:
            tool_name = call["name"]
            tool_args = call["args"].copy()
            tool = self.tools_by_name.get(tool_name)
            
            if not tool: continue
            
            try:
                # Bütçe enjeksiyonu
                if tool_name.startswith("search_") and tool_args.get("max_price") is None:
                    if state.get("target_budget", 0) > 0:
                        tool_args["max_price"] = state["target_budget"] # Basit bütçe kısıtı

                result = tool.invoke(tool_args)
                new_messages.append(ToolMessage(content=str(result), tool_call_id=call["id"], name=tool_name))
                
                # State güncelleme mantığı
                if tool_name == "select_component":
                    import json
                    comp_data = json.loads(tool_args["component_json"])
                    new_selected[tool_args["component_type"]] = comp_data
                elif tool_name == "optimize_build":
                    import json
                    # Wrapper output formati: "=== HAZIR BUILD ÖZETİ ... === \n\nJSON_DATA:\n{...}"
                    json_part = result
                    marker = "JSON_DATA:"
                    if marker in result:
                        json_part = result.split(marker, 1)[1].strip()
                    res = json.loads(json_part)
                    if "selected_components" in res: new_selected.update(res["selected_components"])
            except Exception as e:
                new_messages.append(ToolMessage(content=f"Error: {str(e)}", tool_call_id=call["id"], name=tool_name))
        
        return {"messages": new_messages, "selected_components": new_selected}

def chatbot_node(state: AgentState):
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    # Döngü önleyici: Son mesaj ToolMessage ise context'e göre rehberlik ekle
    if isinstance(state["messages"][-1], ToolMessage):
        tool_content = state["messages"][-1].content
        if "generate_final_report" in (state["messages"][-1].name or ""):
            messages.append(SystemMessage(content="Final rapor yukarıda. Bunu kullanıcıya göster, satın alma linklerini ekle. Başka araç çağırma."))
        elif "select_component" in (state["messages"][-1].name or ""):
            messages.append(SystemMessage(content="Bileşen kaydedildi. Başka araç çağırmadan devam et."))
        else:
            messages.append(SystemMessage(content="Arama sonuçları yukarıda. Kullanıcıya uygun seçenekleri sun ve başka araç çağırmadan onayını bekle."))

    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def validator_node(state: AgentState):
    v = ValidatorNode()
    return v(state)

# --- Graf İnşası ---
def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("chatbot", chatbot_node)
    builder.add_node("tools", BudgetAwareToolNode(ALL_TOOLS))
    builder.add_node("validator", validator_node)

    builder.add_edge(START, "chatbot")
    builder.add_conditional_edges("chatbot", tools_condition)
    builder.add_edge("tools", "validator")
    builder.add_edge("validator", "chatbot")

    return builder.compile(checkpointer=MemorySaver())

GRAPH = build_graph()
