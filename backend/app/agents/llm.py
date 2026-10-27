import tiktoken
from groq import APIConnectionError, RateLimitError
from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq

from app.core.config import settings

# Closest public tokenizer to gpt-oss. Estimates only: quota settles to Groq's real count.
_encoding = tiktoken.get_encoding("o200k_base")

MAX_OUTPUT_TOKENS = 1200
SUMMARY_MAX_OUTPUT_TOKENS = 1800

class LLMUnavailable(Exception):
    """Groq rate-limited us or couldn't be reached (after retries)."""


_llm = ChatGroq(
    model=settings.groq_model,
    api_key=settings.groq_api_key,
    temperature=0.2,
    max_tokens=MAX_OUTPUT_TOKENS,
    reasoning_effort="low",
    max_retries=2,
    timeout=30,
)

def estimate_tokens(messages: list[BaseMessage], max_output: int = MAX_OUTPUT_TOKENS) -> int:
    prompt = sum(len(_encoding.encode(str(m.content))) + 4 for m in messages)
    return prompt + max_output


async def call_llm(messages: list[BaseMessage]) -> tuple[str, int]:
    """Returns (text, total_tokens_used). total_tokens is 0 if Groq didn't report usage."""
    try:
        response = await _llm.ainvoke(messages)
    except (RateLimitError, APIConnectionError) as e:
        raise LLMUnavailable() from e
    usage = response.usage_metadata or {}
    return str(response.content), int(usage.get("total_tokens", 0))

_llm_summary = ChatGroq(
    model=settings.groq_model,
    api_key=settings.groq_api_key,
    temperature=0.2,
    max_tokens=SUMMARY_MAX_OUTPUT_TOKENS,
    reasoning_effort="low",
    max_retries=2,
    timeout=45,
)

async def call_llm_structured(messages: list[BaseMessage], schema: type) -> tuple[object | None, int]:
    """Returns (parsed_object_or_None, total_tokens). None means the model's output didn't fit the schema."""
    runnable = _llm_summary.with_structured_output(schema, method="json_schema", include_raw=True)
    try:
        result = await runnable.ainvoke(messages)
    except (RateLimitError, APIConnectionError) as e:
        raise LLMUnavailable() from e
    usage = getattr(result.get("raw"), "usage_metadata", None) or {}
    return result.get("parsed"), int(usage.get("total_tokens", 0))