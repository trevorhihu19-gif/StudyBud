from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.llm import call_llm, estimate_tokens
from app.agents.prompts import build_messages, finalize_answer
from app.core.database import AsyncSessionLocal
from app.services.quota import llm_quota
from app.services.retrieval import retrieve

TOP_K = 4  # lean context: protects the 8K tokens/minute Groq limit

NO_CONTEXT_ANSWER = (
    "I couldn't find anything relevant in your notes for that. "
    "Try rephrasing, or upload material that covers it."
)


class QAState(TypedDict, total=False):
    question: str
    history: list[dict]
    chunks: list[dict]
    answer: str
    citations: list[dict]


@dataclass
class QAContext:
    user_id: UUID
    document_ids: list[UUID] | None = None


async def retrieve_node(state: QAState, runtime: Runtime[QAContext]) -> dict:
    ctx = runtime.context
    async with AsyncSessionLocal() as db, db.begin():
        results = await retrieve(
            db, user_id=ctx.user_id, query=state["question"], limit=TOP_K, document_ids=ctx.document_ids
        )
    return {
        "chunks": [
            {
                "chunk_id": str(r.chunk_id),
                "document_id": str(r.document_id),
                "page_number": r.page_number,
                "content": r.content,
            }
            for r in results
        ]
    }


def route_after_retrieve(state: QAState) -> Literal["generate", "no_context"]:
    return "generate" if state.get("chunks") else "no_context"


async def generate_node(state: QAState, runtime: Runtime[QAContext]) -> dict:
    messages = build_messages(state["question"], state.get("history", []), state["chunks"])

    async with llm_quota(runtime.context.user_id, estimate_tokens(messages)) as quota:
        text, total_tokens = await call_llm(messages)
        if total_tokens > 0:  # no usage reported -> keep the (conservative) estimate charged
            await quota.settle(total_tokens)

    answer, citations = finalize_answer(text, state["chunks"])
    return {"answer": answer, "citations": citations}


async def no_context_node(state: QAState) -> dict:
    return {"answer": NO_CONTEXT_ANSWER, "citations": []}


def build_qa_graph():
    g = StateGraph(QAState, context_schema=QAContext)
    g.add_node("retrieve", retrieve_node)
    g.add_node("generate", generate_node)
    g.add_node("no_context", no_context_node)
    g.add_edge(START, "retrieve")
    g.add_conditional_edges("retrieve", route_after_retrieve, ["generate", "no_context"])
    g.add_edge("generate", END)
    g.add_edge("no_context", END)
    return g.compile()


qa_graph = build_qa_graph()  # compiled once at import, reused across requests