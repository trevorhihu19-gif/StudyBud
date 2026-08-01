from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.core.security import verify_clerk_token
from app.core.database import get_db
from app.models import User

logger = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)

async def get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        db: AsyncSession = Depends(get_db)
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication token")
    
    claims = await verify_clerk_token(credentials.credentials)
    clerk_id = claims["sub"]

    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            clerk_id=clerk_id,
            email=claims.get("email", f"{clerk_id}@unknown.studybud"),
            name=claims.get("name")
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
            logger.info("user_provisioned", user_id=str(user.id), clerk_id=clerk_id)
        except IntegrityError:
            await db.rollback()
            result = await db.execute(select(User).where(User.clerk_id == clerk_id))
            user = result.scalar_one()

    return user