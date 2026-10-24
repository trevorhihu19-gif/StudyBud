import uuid
from datetime import datetime, timedelta
from functools import partial

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.qa_graph import QAContext, qa_graph
from app.api.deps import get_current_user
from app.core.analytics import track
from app.core.logging import get_logger, request_id_var
from app.core.rate_limit import rate_limit
from app.core.database import get_db
from app.models import ChatMessage, ChatSession, Document, User
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)

@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(partial(rate_limit, requested=3))
):
    history: list[dict] = []
    is_new = body.session_id is None
    
    if is_new:
        session_id = uuid.uuid4()
        document_id = body.document_id
        if document_id:
            owned = await db.execute(select(Document.id).where(Document.id == document_id, Document.user_id == user.id))
            if owned.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Document not found")
            
    else:
        found = await db.execute(
            select(ChatSession).where(ChatSession.id == body.session_id, ChatSession.user_id == user.id)
        )
        existing = found.scalar_one_or_none()
        if existing is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        session_id, document_id = existing.id, existing.document_id
        
        rows = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(6)
        )
        history = [{"role": m.role, "content": m.content} for m in reversed(rows.scalars().all())]
        
    await db.commit()
    
      #2. Run the agent --
    asked_at = datetime.now(datetime.UTC)
    result = await qa_graph.ainvoke(
        {"question": body.message, "history": history},
        context=QAContext(user_id=user.id, document_ids=[document_id] if document_id else None),
        config={
            "tags": ["qa"],
            "metadata": {"user_id": str(user.id), "request_id": request_id_var.get()},  # ids only, never email
        },
    )
    answered_at = max(datetime.now(datetime.UTC), asked_at + timedelta(milliseconds=1))

    #3. Write phase: only reached if the agent succeeded --
    if is_new:
        db.add(ChatSession(id=session_id, user_id=user.id, document_id=document_id, title=body.message[:60]))
        await db.flush()
    db.add(ChatMessage(session_id=session_id, role="user", content=body.message, created_at=asked_at))
    db.add(
        ChatMessage(
            session_id=session_id,
            role="assistant",
            content=result["answer"],
            citations=result["citations"],
            created_at=answered_at,
        )
    )
    await db.commit()

    logger.info(
        "chat_answered",
        user_id=str(user.id),
        session_id=str(session_id),
        citations=len(result["citations"]),
        scoped=document_id is not None,
    )
    track("chat_message_sent", user_id=str(user.id), properties={"scoped": document_id is not None})

    return ChatResponse(session_id=session_id, answer=result["answer"], citations=result["citations"])