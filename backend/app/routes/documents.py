import uuid
from fastapi import APIRouter, Depends, UploadFile, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.analytics import track
from app.core.file_validation import read_and_validate_upload
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import Document, DocumentStatus, User
from app.schemas.document import DocumentResponse
from app.services.storage import save_document_file
from app.services.document_processor import process_document

router = APIRouter(prefix="/documents", tags=["documents"])
logger = get_logger(__name__)

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _:None = Depends(rate_limit)
):
    content = await read_and_validate_upload(file)
    extension = file.filename.rsplit(".", 1)[-1].lower()

    document_id = uuid.uuid4()
    relative_path = await save_document_file(user.id, document_id, extension, content)

    document = Document(
        id=document_id,
        user_id=user.id,
        title=file.filename[:500],
        file_type=extension,
        storage_url=relative_path,
        status=DocumentStatus.PROCESSING
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    
    background_tasks.add_task(process_document, document.id)

    logger.info("document_uploaded", user_id=str(user.id), document_id=str(document.id), file_type=extension)
    track("document_uploaded", user_id=str(user.id), properties={"file_type": extension})
    
    return document
