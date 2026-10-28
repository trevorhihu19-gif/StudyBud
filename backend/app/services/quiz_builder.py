"""Turns the model's raw quiz output into safe, validated questions.

Pure functions only
"""

import random
import re

from app.core.sanitize import clean_generated

_WHITESPACE = re.compile(r"\s+")

def normalize_topic(name: str) -> str:
    """Tidy a topic name the model wrote.

    Cleans it, squeezes repeated spaces, and caps it at 80 characters.

    Args:
        name: The raw topic text from the model.

    Returns:
        The tidy name, or "General" if nothing usable is left.
    """
    
    cleaned = _WHITESPACE.sub(" ", clean_generated(name, 80)).strip()
    return cleaned or "General"

def build_valid_questions(raw_questions: list[dict], chunks: list[dict], max_questions: int) -> list[dict]:
    """Check each model-written question and keep only the trustworthy ones.

    A question is dropped if it is empty or a duplicate, if a multiple-choice
    question doesn't have exactly 4 different options, or if its correct answer
    doesn't match one of the options. Multiple-choice options are shuffled so the
    right answer isn't always in the same position.

    Args:
        raw_questions: The model's questions as plain dicts.
        chunks: The source chunks the model saw (numbered from 1 in the prompt).
        max_questions: Stop once we have this many valid questions.

    Returns:
        A list of clean dicts with: question_type, question_text, options,
        correct_answer, explanation, topic, chunk_id.
    """
    
    seen: set[str] = set()
    valid: list[dict] = []
    
    for q in raw_questions:
        text = clean_generated(q["question"], 500)
        if not text or text.lower() in seen:
            continue
        
        if q["type"] == "true_false":
            answer = q["correct_answer"].strip().capitalize()
            if answer not in ("True", "False"):
                continue
            options, correct = ["True", "False"], answer
        else:
            options = [clean_generated(o, 200) for o in q["options"]]
            if len(options) != 4 or any(not o for o in options) or len({o.lower() for o in options}) != 4:
                continue
            correct = next((o for o in options if o.lower() == q["correct_answer"].strip().lower()), None)
            if correct is None:
                continue
            random.shuffle(options)
            
        source = q["source"]
        chunk = chunks[source - 1] if 1 <= source <= len(chunks) else None
        
        seen.add(text.lower())
        valid.append(
            {
                "question_type": q["type"],
                "question_text": text,
                "options": options,
                "correct_answer": correct,
                "explanation": clean_generated(q["explanation"], 600),
                "topic": normalize_topic(q["topic"]),
                "chunk_id": chunk["chunk_id"] if chunk else None,
            }
        )
        if len(valid) >= max_questions:
            break

    return valid

