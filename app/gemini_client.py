from typing import List, Dict, Any, Optional
import logging
import os
import mimetypes
from datetime import datetime

# Ensure proper import of the types module
try:
    from google import genai
    from google.genai import types
except ImportError:
    try:
        import google.genai as genai
        from google.genai import types
    except ImportError:
        raise ImportError(
            "Failed to import Google Genai SDK. Please install it with: pip install google-genai"
        )

class GeminiClient:
    """Client for Gemini API with key rotation logic"""
    
    def __init__(self, api_keys: List[str]):
        if not api_keys:
            raise ValueError("No Google API keys provided")
        
        self.api_keys = api_keys
        self.current_key_index = 0
        self.max_retries = 2
        self.clients = {}
        self.logger = logging.getLogger("gemini_client")
        
        # Create a client for each API key
        for i, key in enumerate(self.api_keys):
            self.clients[i] = genai.Client(api_key=key)
    
    def _get_current_client(self):
        """Get the current Gemini client"""
        return self.clients[self.current_key_index]
    
    def _rotate_key(self):
        """Rotate to the next API key"""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self.logger.info(f"Rotated to Google API key index: {self.current_key_index}")
        
    def execute_with_retry(self, operation_func, *args, **kwargs):
        """Execute a Gemini API operation with retry logic"""
        retries = 0
        last_error = None
        
        while retries <= self.max_retries:
            try:
                client = self._get_current_client()
                # Get the operation function from the current client
                operation = getattr(client.models, operation_func)
                result = operation(*args, **kwargs)
                # Verify we got a valid response before returning
                if result is None:
                    raise ValueError("Received None response from Gemini API")
                return result
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                
                # More specific check for quota/rate limit errors only
                if any(term in error_msg for term in [
                    "quota exceeded", "rate limit", "resource exhausted", 
                    "too many requests", "resource has been exhausted"
                ]):
                    self.logger.warning(f"API limit reached for key {self.current_key_index}. Rotating key.")
                    self._rotate_key()
                    retries += 1
                else:
                    # For other errors, don't retry
                    self.logger.error(f"Non-retriable error: {error_msg}")
                    break
        
        # If we get here, all retries failed or it was a non-quota error
        raise last_error
    
    def generate_content(self, model: str, contents: Any, config: Optional[Dict] = None):
        """Generate content with automatic key rotation on quota errors"""
        if isinstance(config, dict):
            try:
                config = types.GenerateContentConfig(**config)
            except Exception as e:
                self.logger.error(f"Error creating GenerateContentConfig: {str(e)}")
                raise
            
        return self.execute_with_retry(
            "generate_content",
            model=model,
            contents=contents,
            config=config
        )
    
    def generate_content_stream(self, model: str, contents: Any, config: Optional[Dict] = None):
        """Generate streaming content with automatic key rotation on quota errors"""
        if isinstance(config, dict):
            try:
                config = types.GenerateContentConfig(**config)
            except Exception as e:
                self.logger.error(f"Error creating GenerateContentConfig: {str(e)}")
                raise
            
        return self.execute_with_retry(
            "generate_content_stream",
            model=model,
            contents=contents,
            config=config
        )
    
    def count_tokens(self, model: str, contents: Any):
        """Count tokens with automatic key rotation on quota errors"""
        return self.execute_with_retry(
            "count_tokens",
            model=model,
            contents=contents
        )
    
    def embed_content(self, model: str, contents: Any, config: Optional[Dict] = None):
        """Embed content with automatic key rotation on quota errors"""
        if isinstance(config, dict):
            try:
                config = types.EmbedContentConfig(**config) if config else None
            except Exception as e:
                self.logger.error(f"Error creating EmbedContentConfig: {str(e)}")
                raise
            
        return self.execute_with_retry(
            "embed_content",
            model=model,
            contents=contents,
            config=config
        )
    
    def load_file_to_part(self, file_path: str):
        """
        Load a file from disk and convert it to a Part for Gemini API
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Get file mime type
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"
        
        try:
            # Read file bytes
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            
            # Use the method that was confirmed working in your test
            return types.Part.from_bytes(mime_type=mime_type, data=file_bytes)
            
        except Exception as e:
            self.logger.error(f"Error creating file part: {str(e)}")
            raise
            
    def set_api_key(self, api_key: str):
        """특정 API 키 사용을 위한 설정"""
        if api_key not in self.api_keys:
            raise ValueError("Invalid API key")
        
        # 해당 키의 인덱스 찾기
        for idx, key in enumerate(self.api_keys):
            if key == api_key:
                self.current_key_index = idx
                break
        
        self.logger.debug(f"API 키 설정: 인덱스 {self.current_key_index}")
