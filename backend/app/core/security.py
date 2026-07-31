import jwt
import httpx
from cachetools import TTLCache
from fastapi import HTTPException, status

from app.core.logging import get_logger 
from app.core.config import settings

logger = get_logger(__name__)

_jwks_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)

async def _get_jwks() -> dict:
    if "jwks" in _jwks_cache:
        return _jwks_cache["jwks"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(settings.clerk_jwks_url)
        response.raise_for_status()
        jwks = response.json()

    _jwks_cache["jwks"] = jwks
    return jwks

async def verify_clerk_token(token: str) -> dict:
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if kid is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token header"
                )
        
        jwks = await _get_jwks()
        matching_key = next((k for k in jwks["keys"] if k["kid"] == kid), None)

        if matching_key is None:
            _jwks_cache.clear()
            jwks = await _get_jwks()
            matching_key = next((k for k in jwks["keys"] if k ["kid"] == kid), None)
            if matching_key is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unknown signing key"
                )
        
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching_key)

        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        return claims
    
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")




