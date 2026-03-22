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

⛔ KURALLAR:
1. **BİR KEZ ARA:** Kullanıcı bir parça istediğinde ilgili aracı (`search_...`) BİR KEZ çağır ve sonuçları kullanıcıya sun.
2. **TEKNİK UYUM:** Anakart ararken işlemcinin soketine ve ram tipine dikkat et.
3. **STOK DIŞI:** Eğer kullanıcı "stok önemli değil" derse 'search_reference_library' kullan.
4. **ÜRÜN SEÇİMİ:** Kullanıcı bir ürünü onayladığında 'select_component' ile kilitle.
5. **LİNKLERİ PAYLAŞ:** Veritabanından gelen sonuçlarda 'url' alanı varsa, ürünleri listelerken mutlaka bu satın alma linklerini de Markdown formatında `[Ürün Adı](url)` şeklinde kullanıcıya sun.

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
                    res = json.loads(result)
                    if "selected_components" in res: new_selected.update(res["selected_components"])
            except Exception as e:
                new_messages.append(ToolMessage(content=f"Error: {str(e)}", tool_call_id=call["id"], name=tool_name))
        
        return {"messages": new_messages, "selected_components": new_selected}

def chatbot_node(state: AgentState):
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    # Döngü önleyici: Eğer son mesaj bir ToolMessage ise LLM'e cevap vermesi gerektiğini hatırlat
    if isinstance(state["messages"][-1], ToolMessage):
        messages.append(SystemMessage(content="Arama sonuçları yukarıda. Lütfen kullanıcıya uygun seçenekleri sun ve başka araç çağırmadan önce onayını bekle."))
    
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
