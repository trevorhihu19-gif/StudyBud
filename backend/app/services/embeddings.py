from llama_index.embeddings.huggingface import HuggingFaceEmbedding

_embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

BATCH_SIZE = 32

async def embed_chunks(chunks: list[dict]) -> list[dict]:
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        texts = [c["content"] for c in batch]
        embeddings = _embed_model.get_text_embedding_batch(texts)
        for chunk, embedding in zip(batch, embeddings):
            chunk["embedding"] = embedding
    return chunks
    
