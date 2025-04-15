from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import os

from app.database import get_db
from app.utils.security import get_api_key
from app.file_storage import FileStorage
from app.models import UploadedFile

# Create file storage instance
file_storage = FileStorage()

router = APIRouter(prefix="/api/files", tags=["files"])

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Upload a file for use with Gemini API"""
    try:
        # Save file
        db_file = await file_storage.save_file(file, api_key, db)
        
        # Return file info
        return {
            "id": db_file.id,
            "filename": db_file.filename,
            "mime_type": db_file.mime_type,
            "size": db_file.size,
            "created_at": db_file.created_at
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")

@router.get("/")
async def list_files(
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """List files uploaded by the current API key"""
    files = db.query(UploadedFile).filter(UploadedFile.api_key == api_key).all()
    
    return [
        {
            "id": file.id,
            "filename": file.filename,
            "mime_type": file.mime_type,
            "size": file.size,
            "created_at": file.created_at
        }
        for file in files
    ]

@router.get("/{file_id}")
async def get_file(
    file_id: str,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Get file metadata"""
    file = db.query(UploadedFile).filter(
        UploadedFile.id == file_id,
        UploadedFile.api_key == api_key
    ).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    return {
        "id": file.id,
        "filename": file.filename,
        "mime_type": file.mime_type,
        "size": file.size,
        "created_at": file.created_at
    }

@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Delete a file"""
    file = db.query(UploadedFile).filter(
        UploadedFile.id == file_id,
        UploadedFile.api_key == api_key
    ).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Delete file from disk
    try:
        if os.path.exists(file.storage_path):
            os.remove(file.storage_path)
    except Exception as e:
        # Log error but continue with DB deletion
        print(f"Error deleting file from disk: {str(e)}")
    
    # Delete from database
    db.delete(file)
    db.commit()
    
    return {"message": "File deleted successfully"}
