import os
import uuid
import shutil
from datetime import datetime
from typing import Optional
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import UploadedFile

class FileStorage:
    """Handle file storage operations"""
    
    def __init__(self, upload_dir: str = "uploads"):
        """Initialize with upload directory"""
        self.upload_dir = upload_dir
        os.makedirs(upload_dir, exist_ok=True)
    
    async def save_file(self, file: UploadFile, api_key: str, db: Session) -> UploadedFile:
        """Save uploaded file and return file metadata"""
        # Generate unique filename
        file_uuid = str(uuid.uuid4())
        original_name = file.filename
        ext = os.path.splitext(original_name)[1] if original_name else ""
        filename = f"{file_uuid}{ext}"
        file_path = os.path.join(self.upload_dir, filename)
        
        # Save file to disk
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Create file record in database
        mime_type = file.content_type or "application/octet-stream"
        file_size = os.path.getsize(file_path)
        
        db_file = UploadedFile(
            id=file_uuid,
            filename=original_name,
            storage_path=file_path,
            mime_type=mime_type,
            size=file_size,
            api_key=api_key,
            created_at=datetime.now()
        )
        
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        
        return db_file
    
    def get_file(self, file_id: str, db: Session) -> Optional[UploadedFile]:
        """Get file metadata by ID"""
        return db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    
    def get_file_path(self, file_id: str, db: Session) -> Optional[str]:
        """Get file path by ID"""
        file = self.get_file(file_id, db)
        if file:
            return file.storage_path
        return None
