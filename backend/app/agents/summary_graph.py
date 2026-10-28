from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from app.agents.llm import SUMMARY_MAX_OUTPUT_TOKENS, call_llm_structured, estimate_tokens
from app.agents.prompts import build_summary_messages, strip_unsafe_markup
from app.core.logging import get_logger
from app.services.chunk_selection import select_representative
from app.services.chunk_loader import load_owned_chunks
from app.services.quota import llm_quota

logger = get_logger(__name__)

CONTENT_BUDGET_TOKENS = 3500
MAX_KEY_POINTS = 12

class SummaryGenerationError(Exception):
    """Our own failures (empty doc, unusable model output). Messages are safe to show."""
    
class LLMKeyPoint(BaseModel):
    title: str = Field(description="Short label, at most 8 words")
    explanation: str = Field(description="One or two sentences")
    category: Literal["concept", "definition", "exam_tip"]
    importance: Literal["very_important", "important", "useful"]
    source: int = Field(description="Number of the <source> this point comes from")
    
class LLMSummary(BaseModel):
    overview: str = Field(description="Three to five sentence overview of the material")
    key_points: list[LLMKeyPoint]
    
class SummaryState(TypedDict, total=False):
    document_id: str
    chunks: list[dict]
    chunks_total: int
    overview: str
    key_points: list[dict]
    
@dataclass
class SummaryContext:
    user_id: UUID
    
def _clean(text: str, limit: int) -> str:
    return strip_unsafe_markup(text).strip()[:limit]

async def select_node(state: SummaryState, runtime: Runtime[SummaryContext]) -> dict:
    """Pick the document sections that best represent the whole document.

    Loads the user's chunks (ownership is re-checked inside the loader), then
    keeps a varied, central subset that fits the token budget. No AI call here.

    Returns:
        State update with the chosen "chunks" and the document's "chunks_total".
    """
    all_chunks = await load_owned_chunks(runtime.context.user_id, UUID(state["document_id"]))

    usable = [c for c in all_chunks if c["embedding"] is not None]
    if not usable:
        raise SummaryGenerationError("This document has no readable content to summarize")

    selected = select_representative(usable, CONTENT_BUDGET_TOKENS)
    for c in selected:
        c.pop("embedding")  # big and not needed later; keeps graph state and traces small

    logger.info("chunks_selected", used=len(selected), total=len(all_chunks))
    return {"chunks": selected, "chunks_total": len(all_chunks)}

async def summarize_node(state: SummaryState, runtime: Runtime[SummaryContext]):
    chunks = state["chunks"]
    messages = build_summary_messages(chunks)
    
    async with llm_quota(
        runtime.context.user_id, estimate_tokens(messages, SUMMARY_MAX_OUTPUT_TOKENS)
    ) as quota:
        parsed, total_tokens = await call_llm_structured(messages, LLMSummary)
        if total_tokens > 0:
            await quota.settle(total_tokens)
            
        if parsed is None:
            raise SummaryGenerationError("The model returned an unusable summary. Please try again.")
        
        points = []
        for kp in parsed.key_points[:MAX_KEY_POINTS]:
            src = chunks[kp.source - 1] if 1 <= kp.source <= len(chunks) else None  # ignore invented source numbers
            points.append(
                {
                    "title": _clean(kp.title, 120),
                    "explanation": _clean(kp.explanation, 500),
                    "category": kp.category,
                    "importance": kp.importance,
                    "page": src["page_number"] if src else None,
                    "chunk_id": src["chunk_id"] if src else None,
                }
        )
    return {"overview": _clean(parsed.overview, 1500), "key_points": points}

def build_summary_graph():
    g = StateGraph(SummaryState, context_schema=SummaryContext)
    g.add_node("select", select_node)
    g.add_node("summarize", summarize_node)
    g.add_edge(START, "select")
    g.add_edge("select", "summarize")
    g.add_edge("summarize", END)
    return g.compile()


summary_graph = build_summary_graph()