"""Turns the model's raw flashcards into clean, de-duplicated cards."""

import hashlib
import re

from app.core.sanitize import clean_generated

_NON_WORD = re.compile(r"\W+")


def front_fingerprint(front: str) -> str:
    """Make a short fingerprint of a card's front, used to detect duplicates.

    Ignores capitalization, punctuation and extra spaces, so "What is BCNF?" and
    "what is  bcnf" count as the same card.

    Args:
        front: The question or term on the front of the card.

    Returns:
        A 64-character hex string.
    """
    normalized = _NON_WORD.sub(" ", front.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_valid_cards(raw_cards: list[dict], max_cards: int) -> list[dict]:
    """Clean the model's flashcards and drop unusable or repeated ones.

    A card is dropped if its front is too short, its back is empty, or its front
    matches an earlier card in the same batch.

    Args:
        raw_cards: The model's cards as dicts with "front" and "back".
        max_cards: Stop after this many valid cards.

    Returns:
        A list of dicts with front, back and front_hash.
    """
    seen: set[str] = set()
    valid: list[dict] = []

    for card in raw_cards:
        front = clean_generated(card["front"], 300)
        back = clean_generated(card["back"], 600)
        if len(front) < 5 or not back:
            continue

        fingerprint = front_fingerprint(front)
        if fingerprint in seen:
            continue

        seen.add(fingerprint)
        valid.append({"front": front, "back": back, "front_hash": fingerprint})
        if len(valid) >= max_cards:
            break

    return valid