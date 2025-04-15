from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json
import asyncio
import time
import logging
from typing import Dict, Any, Optional

# Import types
try:
    from google.genai import types
except ImportError:
    from google import genai
    types = genai.types

from app.database import get_db
from app.utils.security import get_api_key
from app.models import UsageLog
from app.client import gemini_client
from app.queue_manager import queue_manager  # Import the shared queue_manager instance

router = APIRouter(prefix="/api", tags=["generation"])

@router.post("/generate")
async def generate_content(
    request: Request,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Generate content using Gemini API with queuing"""
    try:
        # Parse request body
        body = await request.json()
        model = body.get("model")
        contents = body.get("contents")
        config = body.get("config", {})
        wait = body.get("wait", False)  # Option to wait for result
        
        if not model or not contents:
            raise HTTPException(status_code=400, detail="Missing required fields: model, contents")
        
        # Process contents to handle file references
        processed_contents = []
        
        # If contents is a string (simple prompt), wrap in a list
        if isinstance(contents, str):
            processed_contents = [contents]
        elif isinstance(contents, list):
            from app.file_storage import FileStorage
            file_storage = FileStorage()
            
            for item in contents:
                if isinstance(item, str):
                    # For text items, add directly
                    processed_contents.append(item)
                elif isinstance(item, dict) and "file_id" in item:
                    # For file references, load the file
                    file_id = item["file_id"]
                    file_path = file_storage.get_file_path(file_id, db)
                    
                    if not file_path:
                        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
                    
                    try:
                        # Add file part using the confirmed working method
                        file_part = gemini_client.load_file_to_part(file_path)
                        processed_contents.append(file_part)
                        logging.info(f"Successfully loaded file: {file_id}, type: {type(file_part)}")
                    except Exception as e:
                        logging.error(f"Failed to process file {file_id}: {str(e)}", exc_info=True)
                        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")
        else:
            raise HTTPException(status_code=400, detail="Invalid contents format")
        
        # Log what we're sending to Gemini
        logging.info(f"Processed contents: {[type(item) for item in processed_contents]}")
        
        # Add to queue
        args = {
            "model": model,
            "contents": processed_contents,
            "config": config
        }
        
        request_id = queue_manager.enqueue_request(
            api_key=api_key,
            model=model,
            operation="generate_content",
            args=args
        )
        
        # Log queued request
        log = UsageLog(
            api_key=api_key,
            google_api_key_index=gemini_client.current_key_index,
            request_type="generate_content",
            model=model,
            request_size=len(await request.body()),
            response_size=0,
            status="queued"
        )
        db.add(log)
        db.commit()
        
        # If wait=True, wait for result (with reasonable timeout)
        if wait:
            timeout = 120  # 2 minutes timeout
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                status = queue_manager.get_request_status(request_id)
                
                if status and status["status"] in ["completed", "failed"]:
                    if status["status"] == "completed":
                        result = status["result"]
                        
                        # Update log
                        log.status = "success"
                        log.response_size = len(json.dumps({"text": result.text}))
                        db.add(log)
                        db.commit()
                        
                        # Return response
                        return {
                            "text": result.text,
                            "candidates": [
                                {
                                    "content": {
                                        "parts": [{"text": p.text} for p in c.content.parts] 
                                                if (hasattr(c, "content") and hasattr(c.content, "parts")) 
                                                else []
                                    },
                                    "finish_reason": c.finish_reason if hasattr(c, "finish_reason") else None,
                                    "safety_ratings": [
                                        {"category": r.category, "probability": r.probability} 
                                        for r in (c.safety_ratings or [])
                                    ] if (hasattr(c, "safety_ratings") and c.safety_ratings is not None) else []
                                }
                                for c in (result.candidates or [])
                            ] if hasattr(result, "candidates") else []
                        }
                    else:  # failed
                        # Update log
                        log.status = "error"
                        log.error_message = status["error"]
                        db.add(log)
                        db.commit()
                        
                        raise HTTPException(status_code=500, detail=status["error"])
                
                # Wait a bit before checking again
                await asyncio.sleep(1)
            
            # Timeout reached
            raise HTTPException(status_code=408, detail="Request timeout while waiting for result")
        
        # If not waiting, return request ID immediately
        return {
            "request_id": request_id,
            "status": "queued"
        }
        
    except Exception as e:
        # Log error
        log = UsageLog(
            api_key=api_key,
            google_api_key_index=gemini_client.current_key_index if hasattr(gemini_client, "current_key_index") else 0,
            request_type="generate_content",
            model=model if 'model' in locals() else None,
            request_size=len(await request.body()),
            response_size=0,
            status="error",
            error_message=str(e)
        )
        db.add(log)
        db.commit()
        
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{request_id}")
async def get_request_status(
    request_id: str,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Get the status of a queued request"""
    status = queue_manager.get_request_status(request_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Request not found")
    
    if status["status"] == "completed":
        result = status["result"]
        
        # For completed requests, return the full result
        return {
            "status": "completed",
            "text": result.text if hasattr(result, "text") else "",
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": p.text} for p in c.content.parts] 
                                if (hasattr(c, "content") and hasattr(c.content, "parts")) 
                                else []
                    },
                    "finish_reason": c.finish_reason if hasattr(c, "finish_reason") else None,
                    "safety_ratings": [
                        {"category": r.category, "probability": r.probability} 
                        for r in (c.safety_ratings or [])
                    ] if (hasattr(c, "safety_ratings") and c.safety_ratings is not None) else []
                }
                for c in (result.candidates or [])
            ] if hasattr(result, "candidates") else []
        }
    elif status["status"] == "failed":
        return {
            "status": "failed",
            "error": status["error"]
        }
    else:
        # For pending or processing, just return the status
        return {
            "status": status["status"],
            "timestamp": status["timestamp"]
        }

# Update streaming endpoint to use queue as well
@router.post("/generate-stream")
async def generate_content_stream(
    request: Request,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Generate streaming content using Gemini API with queuing"""
    try:
        # Parse request body
        body = await request.json()
        model = body.get("model")
        contents = body.get("contents")
        config = body.get("config", {})
        wait = body.get("wait", True)  # Default to wait for streaming
        
        if not model or not contents:
            raise HTTPException(status_code=400, detail="Missing required fields: model, contents")
        
        # Streaming always uses wait=True (synchronous)
        if not wait:
            raise HTTPException(
                status_code=400, 
                detail="Streaming requires wait=True. Asynchronous streaming is not supported."
            )
        
        # Add to queue
        args = {
            "model": model,
            "contents": contents,
            "config": config
        }
        
        request_id = queue_manager.enqueue_request(
            api_key=api_key,
            model=model,
            operation="generate_content_stream",
            args=args
        )
        
        # Log queued request
        log = UsageLog(
            api_key=api_key,
            google_api_key_index=gemini_client.current_key_index,
            request_type="generate_content_stream",
            model=model,
            request_size=len(await request.body()),
            response_size=0,
            status="queued"
        )
        db.add(log)
        db.commit()
        
        # Wait for result (with timeout)
        async def stream_generator():
            timeout = 180  # 3 minutes timeout for streaming
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                status = queue_manager.get_request_status(request_id)
                
                if status and status["status"] in ["completed", "failed"]:
                    if status["status"] == "completed":
                        # Update log
                        log.status = "success"
                        db.add(log)
                        db.commit()
                        
                        # Stream the result
                        stream = status["result"]
                        try:
                            for chunk in stream:
                                yield json.dumps({"chunk": chunk.text}) + "\n"
                        except Exception as e:
                            yield json.dumps({"error": str(e)}) + "\n"
                    else:  # failed
                        # Update log
                        log.status = "error"
                        log.error_message = status["error"]
                        db.add(log)
                        db.commit()
                        
                        yield json.dumps({"error": status["error"]}) + "\n"
                    
                    # Done streaming, break the loop
                    break
                
                # Wait a bit before checking again
                await asyncio.sleep(1)
            
            # Check if timeout was reached
            if time.time() - start_time >= timeout:
                yield json.dumps({"error": "Request timeout while waiting for result"}) + "\n"
        
        return StreamingResponse(
            stream_generator(),
            media_type="application/x-ndjson"
        )
        
    except Exception as e:
        # Log error
        log = UsageLog(
            api_key=api_key,
            google_api_key_index=gemini_client.current_key_index,
            request_type="generate_content_stream",
            model=model if 'model' in locals() else None,
            request_size=len(await request.body()),
            response_size=0,
            status="error",
            error_message=str(e)
        )
        db.add(log)
        db.commit()
        
        raise HTTPException(status_code=500, detail=str(e))
