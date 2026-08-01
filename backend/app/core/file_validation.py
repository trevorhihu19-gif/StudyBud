import filetype
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  
}
CHUNK_SIZE = 1024 * 1024

async def read_and_validate_upload(file: UploadFile) -> bytes:
    """
    Reads an uploaded file in bounded chunks, enforcing the size cap DURING
    the read (not after) so an oversized upload is rejected before it's
    fully buffered anywhere. Then validates the real file type from its
    magic bytes, ignoring whatever the client claims.
    """
    original_name = file.filename or ""
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    content = bytearray()

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds {settings.max_upload_size_mb}MB limit"
            )
        
    content_bytes = bytes(content)

    if extension == "txt":
        if b"\x00" in content_bytes:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File content is not valid text")
        try:
            content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File content is not valid UTF-8 text")
    else:
        # pdf / docx — verify actual binary signature matches the claimed extension
        kind = filetype.guess(content_bytes)
        if kind is None or kind.mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content does not match its extension",
            )

    return content_bytes
