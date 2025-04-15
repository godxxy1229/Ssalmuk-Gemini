from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import secrets
import string

from app.database import get_db
from app.models import ApiKey, UsageLog
from app.api_key_manager import generate_secure_key

router = APIRouter(prefix="/admin", tags=["admin"])

class ApiKeyResponse(BaseModel):
    id: int
    key: str
    active: bool
    created_at: str
    last_used_at: Optional[str] = None

class ApiKeyCreate(BaseModel):
    count: int = 1

class ApiKeyStatusUpdate(BaseModel):
    active: bool

@router.get("/keys", response_model=List[ApiKeyResponse])
async def list_api_keys(
    skip: int = 0, 
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all API keys (protected endpoint)"""
    # In production, add authentication for admin
    keys = db.query(ApiKey).offset(skip).limit(limit).all()
    
    return [
        ApiKeyResponse(
            id=key.id,
            key=key.key,
            active=key.active,
            created_at=key.created_at.isoformat(),
            last_used_at=key.last_used_at.isoformat() if key.last_used_at else None
        ) 
        for key in keys
    ]

@router.post("/keys", response_model=List[ApiKeyResponse])
async def create_api_keys(
    key_request: ApiKeyCreate,
    db: Session = Depends(get_db)
):
    """Create new API keys (protected endpoint)"""
    # In production, add authentication for admin
    if key_request.count < 1 or key_request.count > 100:
        raise HTTPException(status_code=400, detail="Count must be between 1 and 100")
    
    created_keys = []
    for _ in range(key_request.count):
        key = generate_secure_key()
        db_key = ApiKey(key=key)
        db.add(db_key)
        created_keys.append(db_key)
    
    db.commit()
    
    # Refresh to get IDs
    for key in created_keys:
        db.refresh(key)
    
    return [
        ApiKeyResponse(
            id=key.id,
            key=key.key,
            active=key.active,
            created_at=key.created_at.isoformat(),
            last_used_at=key.last_used_at.isoformat() if key.last_used_at else None
        )
        for key in created_keys
    ]

@router.put("/keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: int,
    key_update: ApiKeyStatusUpdate,
    db: Session = Depends(get_db)
):
    """Update API key status (protected endpoint)"""
    # In production, add authentication for admin
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    key.active = key_update.active
    db.commit()
    db.refresh(key)
    
    return ApiKeyResponse(
        id=key.id,
        key=key.key,
        active=key.active,
        created_at=key.created_at.isoformat(),
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None
    )

@router.get("/logs")
async def get_usage_logs(
    skip: int = 0,
    limit: int = 100,
    api_key: Optional[str] = None,
    request_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get usage logs (protected endpoint)"""
    # In production, add authentication for admin
    query = db.query(UsageLog)
    
    if api_key:
        query = query.filter(UsageLog.api_key == api_key)
    
    if request_type:
        query = query.filter(UsageLog.request_type == request_type)
        
    if status:
        query = query.filter(UsageLog.status == status)
    
    logs = query.order_by(UsageLog.timestamp.desc()).offset(skip).limit(limit).all()
    
    return logs