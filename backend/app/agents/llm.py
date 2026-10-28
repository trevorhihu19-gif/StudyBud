import tiktoken
from functools import lru_cache
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


@lru_cache(maxsize=8)
def _structured_llm(max_tokens: int, temperature: float) -> ChatGroq:
    """Build (and remember) a Groq model client with the given limits.

    Clients are cached so we don't rebuild one on every request. Different
    features can ask for different output sizes and creativity levels.

    Args:
        max_tokens: Most tokens the model may write in its reply.
        temperature: 0 = very predictable, higher = more varied wording.

    Returns:
        A ready-to-use ChatGroq client.
    """
    return ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort="low",
        max_retries=2,
        timeout=45,
    )


async def call_llm_structured(
    messages: list[BaseMessage],
    schema: type,
    max_output_tokens: int = SUMMARY_MAX_OUTPUT_TOKENS,
    temperature: float = 0.2,
) -> tuple[object | None, int]:
    """Ask the model for an answer that must fit a fixed data shape (JSON schema).

    Args:
        messages: The conversation to send to the model.
        schema: A Pydantic class describing exactly what the reply must look like.
        max_output_tokens: Cap on the length of the reply.
        temperature: Wording variety (higher = more varied).

    Returns:
        (parsed_object, total_tokens). parsed_object is None if the reply
        didn't fit the schema; total_tokens is 0 if Groq didn't report usage.

    Raises:
        LLMUnavailable: Groq is rate-limiting us or can't be reached.
    """
    llm = _structured_llm(max_output_tokens, temperature)
    runnable = llm.with_structured_output(schema, method="json_schema", include_raw=True)
    try:
        result = await runnable.ainvoke(messages)
    except (RateLimitError, APIConnectionError) as e:
        raise LLMUnavailable() from e
    usage = getattr(result.get("raw"), "usage_metadata", None) or {}
    return result.get("parsed"), int(usage.get("total_tokens", 0))