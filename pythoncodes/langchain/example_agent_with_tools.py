#═════════════════════| INSTALLATIONS |═════════════════════════════════
import getpass
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from venv_manager import install_deps
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
packages = [
    "langchain", "langchain-community", "langchain-core",
    "langchain-openai", "langgraph", "faiss-cpu", "pypdf",
    "presidio-analyzer", "presidio-anonymizer", "openai",
]
install_deps(packages)
#═════════════════════| IMPORTS |═════════════════════════════════
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langchain_core.messages import HumanMessage
import operator

#═════════════════════| OPENAI SETUP |═════════════════════════════════
llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key= getpass.getpass("OPENAI_API_KEY: "),
    temperature=0
)

#═════════════════════| TOOLS SETUOP |═════════════════════════════════
@tool
def weather_tool(city: str) -> str:
    """Get weather information."""
    return f"The weather in {city} is 32°C and sunny."

@tool
def stock_tool(company: str) -> str:
    """Get stock information."""
    return f"{company} stock price is currently $245."

@tool
def math_tool(expression: str) -> str:
    """Perform math calculations."""
    return f"Result of {expression} = 42"

tools = [weather_tool, stock_tool, math_tool]

#═════════════════════| STATE SETUP |═════════════════════════════════

class AgentState(TypedDict):
    query: str
    tool_outputs: Annotated[list, operator.add]
    final_answer: str


#═════════════════════| ROUTER AGENT |═════════════════════════════════

def router_agent(state: AgentState):

    query = state["query"].lower()
    print(f"Routing query: {query}")
    outputs = []

    if "weather" in query:
        result = weather_tool.invoke("Chennai")
        outputs.append(result)
    print(outputs)
    if "stock" in query or "share" in query:
        result = stock_tool.invoke("Apple")
        outputs.append(result)
    print(outputs)
    if "calculate" in query or "math" in query:
        result = math_tool.invoke("25 * 4")
        outputs.append(result)
    print(outputs)
    return {
        "tool_outputs": outputs
    }

#═════════════════════| FINAL RESPONSE AGENT |═════════════════════════════════

def response_agent(state: AgentState):
    combined_info = "\n".join(state["tool_outputs"])
    
    prompt = f"""
    User Query:
    
    {state['query']}

    Tool Results:
    {combined_info}

    Create a clean final response.
    """

    response = llm.invoke([HumanMessage(content=prompt)])

    return {
        "final_answer": response.content
    }

#═════════════════════| BUILD GRAPH |═════════════════════════════════

builder = StateGraph(AgentState)

builder.add_node("router_agent", router_agent)
builder.add_node("response_agent", response_agent)

builder.set_entry_point("router_agent")

builder.add_edge("router_agent", "response_agent")
builder.add_edge("response_agent", END)

graph = builder.compile()

#═════════════════════| RUN |═════════════════════════════════

query = """
What is the weather in Chennai,
Apple stock price,
and calculate 25 * 4
"""

result = graph.invoke({
    "query": query,
    "tool_outputs": []
})

print("\nFINAL ANSWER:\n")
print(result["final_answer"])
  