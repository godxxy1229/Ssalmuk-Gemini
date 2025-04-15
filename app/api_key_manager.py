import secrets
import string
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional

from app.models import ApiKey, Base
from app.database import engine, SessionLocal

# Create tables
Base.metadata.create_all(bind=engine)

def generate_secure_key(length: int = 32) -> str:
    """Generate a cryptographically secure API key"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def create_api_keys(num_keys: int = 100) -> List[str]:
    """Generate and store API keys in the database"""
    db = SessionLocal()
    keys_created = []
    
    # Count existing keys
    existing_count = db.query(ApiKey).count()
    keys_to_generate = max(0, num_keys - existing_count)
    
    # Generate new keys if needed
    for _ in range(keys_to_generate):
        key = generate_secure_key()
        db_key = ApiKey(key=key)
        db.add(db_key)
        keys_created.append(key)
    
    db.commit()
    db.close()
    
    return keys_created

def validate_api_key(db: Session, api_key: str) -> Optional[ApiKey]:
    """Validate an API key and update last used timestamp"""
    key = db.query(ApiKey).filter(ApiKey.key == api_key, ApiKey.active == True).first()
    
    if key:
        # Update last used timestamp
        key.last_used_at = datetime.now()
        db.commit()
        
    return key