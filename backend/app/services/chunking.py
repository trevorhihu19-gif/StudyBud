import tiktoken
from llama_index.core import Document as LIDocument
from llama_index.core.node_parser import SentenceSplitter

_encoding = tiktoken.get_encoding("cl100k_base")
_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)

def chunk_documents(pages: list[LIDocument]) -> list[dict]:
    """
    Splits page-level documents into overlapping chunks, preserving page
    numbers from the source. Returns plain dicts ready to become
    DocumentChunk rows — no ORM objects here, keeps this function testable
    without a database.
    """
    
    nodes = _splitter.get_nodes_from_documents(pages)
    
    chunks = []
    for i, node in enumerate(nodes):
        content = node.get_content()
        page_label = node.metadata.get("page_label")
        chunks.append({
                "chunk_index": i,
                "page_number": int(page_label) if page_label and page_label.isdigit() else None,
                "content": content,
                "token_count": len(_encoding.encode(content)),
        })
        return chunks
    
    