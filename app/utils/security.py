from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import get_db
from app.api_key_manager import validate_api_key

# API key header scheme
api_key_header = APIKeyHeader(name="X-API-Key")

async def get_api_key(
    api_key: str = Depends(api_key_header),
    db: Session = Depends(get_db)
):
    """Dependency to verify API key and return it if valid"""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key"
        )
    
    db_key = validate_api_key(db, api_key)
    if not db_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return api_key