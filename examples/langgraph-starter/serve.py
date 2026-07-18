"""Serve a LangGraph agent behind one HTTP endpoint so ProveKit can test it.

ProveKit never imports your code — it just POSTs to this endpoint and asserts on the
response. In your project, delete the example graph below and use your own:

    from my_agent import graph   # your compiled StateGraph

Run:
    pip install -r requirements.txt
    export OPENAI_API_KEY=sk-...          # only needed by the example graph
    uvicorn serve:app --port 8000
"""
from fastapi import FastAPI

# --- your agent -------------------------------------------------------------------------
# Replace this whole block with:  from my_agent import graph
# Example: a trivial single-node LangGraph agent that answers with an LLM.
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

_llm = ChatOpenAI(model="gpt-4o-mini")


def _call_model(state: MessagesState):
    return {"messages": [_llm.invoke(state["messages"])]}


_builder = StateGraph(MessagesState)
_builder.add_node("model", _call_model)
_builder.add_edge(START, "model")
_builder.add_edge("model", END)
graph = _builder.compile()
# ----------------------------------------------------------------------------------------

app = FastAPI(title="LangGraph agent (ProveKit demo)")


@app.post("/invoke")
def invoke(body: dict):
    """{"input": "..."} -> {"output": "..."} — the shape the ProveKit tests expect."""
    result = graph.invoke({"messages": [("user", body["input"])]})
    return {"output": result["messages"][-1].content}
