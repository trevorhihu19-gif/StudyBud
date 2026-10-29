"""LangGraph workflow that writes flashcards from a document: select chunks, then generate."""

from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel

from app.agents.llm import call_llm_structured, estimate_tokens
from app.agents.prompts import build_flashcard_messages
from app.core.logging import get_logger
from app.services.chunk_loader import load_study_sample
from app.services.flashcard_builder import build_valid_cards
from app.services.quota import llm_quota

logger = get_logger(__name__)

CONTENT_BUDGET_TOKENS = 3000
OUTPUT_TOKENS_PER_CARD = 120
OUTPUT_OVERHEAD_TOKENS = 300
MIN_VALID_CARDS = 3
SAMPLE_FRACTION = 0.7


class FlashcardGenerationError(Exception):
    """Our own failures (empty document, unusable model output). Messages are safe to show users."""


class LLMCard(BaseModel):
    """One flashcard exactly as we ask the model to write it."""

    front: str
    back: str


class LLMCards(BaseModel):
    """The full reply shape we require from the model."""

    cards: list[LLMCard]


class FlashcardState(TypedDict, total=False):
    """Data passed between the steps of the graph."""

    document_id: str
    num_cards: int
    chunks: list[dict]
    cards: list[dict]


@dataclass
class FlashcardContext:
    """Per-run info that isn't part of the graph's data: who is asking."""

    user_id: UUID


async def select_node(state: FlashcardState, runtime: Runtime[FlashcardContext]) -> dict:
    """Choose which parts of the document the flashcards will be based on.

    Returns:
        State update with the chosen "chunks".

    Raises:
        FlashcardGenerationError: The document has no usable content.
    """
    chunks = await load_study_sample(
        runtime.context.user_id, UUID(state["document_id"]), CONTENT_BUDGET_TOKENS, SAMPLE_FRACTION
    )
    if not chunks:
        raise FlashcardGenerationError("This document has no readable content to make flashcards from")
    return {"chunks": chunks}


async def generate_node(state: FlashcardState, runtime: Runtime[FlashcardContext]) -> dict:
    """Ask the model for flashcards, then clean and de-duplicate them in code.

    The token quota is reserved first and corrected to the real usage afterwards.
    An unusable reply is not refunded, because the tokens were really spent.

    Returns:
        State update with the validated "cards".

    Raises:
        FlashcardGenerationError: Reply didn't fit the schema, or too few valid cards.
    """
    chunks, wanted = state["chunks"], state["num_cards"]
    messages = build_flashcard_messages(chunks, wanted)
    max_output = OUTPUT_TOKENS_PER_CARD * wanted + OUTPUT_OVERHEAD_TOKENS

    async with llm_quota(runtime.context.user_id, estimate_tokens(messages, max_output)) as quota:
        parsed, total_tokens = await call_llm_structured(
            messages, LLMCards, max_output_tokens=max_output, temperature=0.4
        )
        if total_tokens > 0:
            await quota.settle(total_tokens)

    if parsed is None:
        raise FlashcardGenerationError("The model returned unusable flashcards. Please try again.")

    cards = build_valid_cards([c.model_dump() for c in parsed.cards], wanted)
    logger.info("flashcards_validated", requested=wanted, returned=len(parsed.cards), kept=len(cards))

    if len(cards) < MIN_VALID_CARDS:
        raise FlashcardGenerationError("Couldn't build reliable flashcards from this document. Please try again.")
    return {"cards": cards}


def build_flashcard_graph():
    """Wire the two steps together: START -> select -> generate -> END.

    Returns:
        The compiled graph, ready to run.
    """
    g = StateGraph(FlashcardState, context_schema=FlashcardContext)
    g.add_node("select", select_node)
    g.add_node("generate", generate_node)
    g.add_edge(START, "select")
    g.add_edge("select", "generate")
    g.add_edge("generate", END)
    return g.compile()


flashcard_graph = build_flashcard_graph()  # built once at startup, reused by every request