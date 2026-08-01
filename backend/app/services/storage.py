import uuid
from pathlib import Path
import aiofiles

from app.core.config import settings

STORAGE_ROOT = Path(settings.storage_dir).resolve()
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

async def save_document_file(user_id: uuid.UUID, document_id: uuid.UUID, extension: str, content: bytes) -> str:
    """
    Saves file content under a per-user folder, using a fully generated
    filename (document_id + extension). The original filename is NEVER
    used to construct a path — it's kept only as a display label in the DB.
    """
    user_folder = STORAGE_ROOT / str(user_id)
    user_folder.mkdir(parents=True, exist_ok=True)

    safe_filename = f"{document_id}.{extension}"
    file_path = user_folder / safe_filename

    if not file_path.resolve().is_relative_to(STORAGE_ROOT):
        raise ValueError("Resolved path escapes storage root")

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    return str(file_path.relative_to(STORAGE_ROOT))