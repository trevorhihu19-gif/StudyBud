import numpy as np


def select_representative(chunks: list[dict], budget_tokens: int, diversity: float = 0.4) -> list[dict]:
    """
    Picks chunks that best cover the document within a token budget, using MMR.
    Each chunk dict needs: embedding, token_count, chunk_index.
    Returns the selection in reading order.
    """
    if sum(c["token_count"] for c in chunks) <= budget_tokens:
        return sorted(chunks, key=lambda c: c["chunk_index"])

    emb = np.array([c["embedding"] for c in chunks], dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    centroid = emb.mean(axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-9
    relevance = emb @ centroid  # how central each chunk is to the whole document

    selected: list[int] = []
    remaining = set(range(len(chunks)))
    used_tokens = 0
    max_sim_to_selected = np.zeros(len(chunks), dtype=np.float32)

    while remaining:
        fits = [i for i in remaining if used_tokens + chunks[i]["token_count"] <= budget_tokens]
        if not fits:
            break
        best = max(fits, key=lambda i: (1 - diversity) * relevance[i] - diversity * max_sim_to_selected[i])
        selected.append(best)
        remaining.discard(best)
        used_tokens += chunks[best]["token_count"]
        max_sim_to_selected = np.maximum(max_sim_to_selected, emb @ emb[best])

    return sorted((chunks[i] for i in selected), key=lambda c: c["chunk_index"])