"""LangGraph workflow that writes a quiz from a document: select chunks, then generate."""

import random
from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from app.agents.llm import call_llm_structured, estimate_tokens
from app.agents.prompts import build_quiz_messages
from app.core.logging import get_logger
from app.services.chunk_loader import load_owned_chunks
from app.services.chunk_selection import select_representative
from app.services.quiz_builder import build_valid_questions
from app.services.quota import llm_quota

logger = get_logger(__name__)

CONTENT_BUDGET_TOKENS = 3000        # how much document text the model sees
OUTPUT_TOKENS_PER_QUESTION = 350    # room the model gets per question
OUTPUT_OVERHEAD_TOKENS = 300
MIN_VALID_QUESTIONS = 3             # below this the quiz isn't worth keeping
SAMPLE_FRACTION = 0.7               # random slice of chunks, so each quiz differs


class QuizGenerationError(Exception):
    """Our own failures (empty document, unusable model output). Messages are safe to show users."""


class LLMQuestion(BaseModel):
    """One question exactly as we ask the model to write it."""

    type: Literal["multiple_choice", "true_false"]
    question: str
    options: list[str] = Field(description="Exactly 4 options for multiple_choice; empty list for true_false")
    correct_answer: str
    explanation: str
    topic: str = Field(description="2-4 word name of the concept tested")
    source: int = Field(description="Number of the <source> the question came from")


class LLMQuiz(BaseModel):
    """The full reply shape we require from the model."""

    questions: list[LLMQuestion]


class QuizState(TypedDict, total=False):
    """Data passed between the steps of the graph."""

    document_id: str
    num_questions: int
    chunks: list[dict]
    questions: list[dict]


@dataclass
class QuizContext:
    """Per-run info that isn't part of the graph's data: who is asking."""

    user_id: UUID


async def select_node(state: QuizState, runtime: Runtime[QuizContext]) -> dict:
    """Choose which parts of the document the quiz will be based on.

    Takes a random 70% of the chunks (so repeat quizzes differ), then picks a
    varied, representative set that fits the token budget. No AI call here.

    Returns:
        State update with the chosen "chunks".
    """
    all_chunks = await load_owned_chunks(runtime.context.user_id, UUID(state["document_id"]))
    usable = [c for c in all_chunks if c["embedding"] is not None]
    if not usable:
        raise QuizGenerationError("This document has no readable content to build a quiz from")

    if len(usable) > 10:
        usable = random.sample(usable, int(len(usable) * SAMPLE_FRACTION))

    selected = select_representative(usable, CONTENT_BUDGET_TOKENS)
    for c in selected:
        c.pop("embedding")
    return {"chunks": selected}


async def generate_node(state: QuizState, runtime: Runtime[QuizContext]) -> dict:
    """Ask the model for questions, then validate every one of them in code.

    The token quota is reserved before the call and corrected to the real usage
    afterwards. If the model's answer is unusable we raise an error without a
    refund, because the tokens really were spent.

    Returns:
        State update with the validated "questions".

    Raises:
        QuizGenerationError: Output didn't fit the schema, or too few valid questions.
    """
    chunks, wanted = state["chunks"], state["num_questions"]
    messages = build_quiz_messages(chunks, wanted)
    max_output = OUTPUT_TOKENS_PER_QUESTION * wanted + OUTPUT_OVERHEAD_TOKENS

    async with llm_quota(runtime.context.user_id, estimate_tokens(messages, max_output)) as quota:
        parsed, total_tokens = await call_llm_structured(
            messages, LLMQuiz, max_output_tokens=max_output, temperature=0.6
        )
        if total_tokens > 0:
            await quota.settle(total_tokens)

    if parsed is None:
        raise QuizGenerationError("The model returned an unusable quiz. Please try again.")

    questions = build_valid_questions([q.model_dump() for q in parsed.questions], chunks, wanted)
    logger.info("quiz_validated", requested=wanted, returned=len(parsed.questions), kept=len(questions))

    if len(questions) < MIN_VALID_QUESTIONS:
        raise QuizGenerationError("Couldn't build a reliable quiz from this document. Please try again.")
    return {"questions": questions}


def build_quiz_graph():
    """Wire the two steps together: START -> select -> generate -> END.

    Returns:
        The compiled graph, ready to run.
    """
    g = StateGraph(QuizState, context_schema=QuizContext)
    g.add_node("select", select_node)
    g.add_node("generate", generate_node)
    g.add_edge(START, "select")
    g.add_edge("select", "generate")
    g.add_edge("generate", END)
    return g.compile()


quiz_graph = build_quiz_graph()  # built once at startup, reused by every request