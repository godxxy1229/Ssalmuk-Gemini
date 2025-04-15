from sqlalchemy import Column, String, Integer, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class ApiKey(Base):
    """Model for storing API keys"""
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    last_used_at = Column(DateTime, nullable=True)
    
class UsageLog(Base):
    """Model for storing API usage logs"""
    __tablename__ = "usage_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    api_key = Column(String, index=True)
    google_api_key_index = Column(Integer)  # Store index rather than actual key for security
    request_type = Column(String)  # generate, embed, count_tokens, etc.
    model = Column(String)
    request_size = Column(Integer)  # Size in bytes
    response_size = Column(Integer)  # Size in bytes
    tokens_used = Column(Integer, nullable=True)
    status = Column(String)  # success, error
    error_message = Column(String, nullable=True)
    timestamp = Column(DateTime, default=func.now())
    
class UploadedFile(Base):
    """Model for storing uploaded files metadata"""
    __tablename__ = "uploaded_files"
    
    id = Column(String, primary_key=True)
    filename = Column(String)
    storage_path = Column(String)
    mime_type = Column(String)
    size = Column(Integer)
    api_key = Column(String, index=True)
    created_at = Column(DateTime, default=func.now())
    ttl = Column(Integer, default=86400)  # Time-to-live in seconds (24 hours default)
