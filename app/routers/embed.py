from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import json

from app.database import get_db
from app.utils.security import get_api_key
from app.models import UsageLog

# Import the client instance from main
from app.client import gemini_client

router = APIRouter(prefix="/api", tags=["embedding"])

@router.post("/embed")
async def embed_content(
    request: Request,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Generate embeddings using Gemini API"""
    try:
        # Parse request body
        body = await request.json()
        model = body.get("model")
        contents = body.get("contents")
        config = body.get("config", {})
        
        if not model or not contents:
            raise HTTPException(status_code=400, detail="Missing required fields: model, contents")
        
        # Generate embeddings
        response = gemini_client.embed_content(
            model=model,
            contents=contents,
            config=config
        )
        
        # Prepare response data
        embeddings = []
        if hasattr(response, 'embeddings'):
            embeddings = [
                {"values": e.values if hasattr(e, "values") else []} 
                for e in response.embeddings
            ]
        
        # Log usage
        request_size = len(await request.body())
        response_size = len(json.dumps({"embeddings": embeddings}))
        
        log = UsageLog(
            api_key=api_key,
            google_api_key_index=gemini_client.current_key_index,
            request_type="embed_content",
            model=model,
            request_size=request_size,
            response_size=response_size,
            status="success"
        )
        db.add(log)
        db.commit()
        
        # Return response
        return {"embeddings": embeddings}
        
    except Exception as e:
        # Log error
        log = UsageLog(
            api_key=api_key,
            google_api_key_index=gemini_client.current_key_index,
            request_type="embed_content",
            model=model if 'model' in locals() else None,
            request_size=len(await request.body()),
            response_size=0,
            status="error",
            error_message=str(e)
        )
        db.add(log)
        db.commit()
        
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/count-tokens")
async def count_tokens(
    request: Request,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Count tokens using Gemini API"""
    try:
        # Parse request body
        body = await request.json()
        model = body.get("model")
        contents = body.get("contents")
        
        if not model or not contents:
            raise HTTPException(status_code=400, detail="Missing required fields: model, contents")
        
        # Count tokens
        response = gemini_client.count_tokens(
            model=model,
            contents=contents
        )
        
        # Prepare response
        token_count = response.total_tokens if hasattr(response, "total_tokens") else 0
        
        # Log usage
        request_size = len(await request.body())
        response_size = len(json.dumps({"total_tokens": token_count}))
        
        log = UsageLog(
            api_key=api_key,
            google_api_key_index=gemini_client.current_key_index,
            request_type="count_tokens",
            model=model,
            request_size=request_size,
            response_size=response_size,
            tokens_used=token_count,
            status="success"
        )
        db.add(log)
        db.commit()
        
        # Return response
        return {"total_tokens": token_count}
        
    except Exception as e:
        # Log error
        log = UsageLog(
            api_key=api_key,
            google_api_key_index=gemini_client.current_key_index,
            request_type="count_tokens",
            model=model if 'model' in locals() else None,
            request_size=len(await request.body()),
            response_size=0,
            status="error",
            error_message=str(e)
        )
        db.add(log)
        db.commit()
        
        raise HTTPException(status_code=500, detail=str(e))
