from pathlib import Path

from llama_index.core import Document as LIDocument
from llama_index.readers.file import DocxReader, PDFReader

from app.core.config import settings

class ExtractionError(Exception):
    pass


def extract_pages(file_path, file_type: str) -> list[LIDocument]:
    """
    Returns a list of LlamaIndex Documents, one per page for PDF (page
    number in metadata), one document total for docx/txt.
    Raises ExtractionError on corrupt files or oversized extracted content.
    """

    try:
        if file_type == "pdf":
            docs = PDFReader().load_data(file=file_path)
        elif file_type == "docx":
            docs = DocxReader().load_data(file=file_path)
        elif file_type == "txt":
            text = file_path.read_text(encoding="utf-8")
            docs = [LIDocument(text=text, metadata={})]
        else:
            raise ExtractionError(f"Unsupported file type: {file_type}")
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            f"Failed to extract content from {file_type} file"
        ) from exc

    total_chars = sum(len(d.text) for d in docs)

    if total_chars > settings.max_extracted_chars:
        raise ExtractionError(
            f"Extracted content ({total_chars} chars) exceeds the "
            f"{settings.max_extracted_chars} char limit"
        )

    if total_chars == 0:
        raise ExtractionError("No extractable text found in document")

    return docs