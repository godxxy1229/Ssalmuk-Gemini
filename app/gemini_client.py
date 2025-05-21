from typing import List, Dict, Any, Optional
import logging
import os
import mimetypes
from datetime import datetime
import time
try:
    from google.api_core import exceptions as google_exceptions
except ImportError:
    google_exceptions = None # Placeholder if not available
    logging.warning("Failed to import google.api_core.exceptions. Specific server error types may not be caught.")


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
        self.max_retries = 2 # Max retries for key rotation
        self.clients = {}
        self.logger = logging.getLogger("gemini_client")
        self.server_error_retries = 0
        self.quota_error_retries = 0
        self.total_api_calls = 0
        self.successful_api_calls = 0
        
        # Create a client for each API key
        for i, key in enumerate(self.api_keys):
            try:
                self.clients[i] = genai.Client(api_key=key)
                self.logger.info(f"Successfully initialized client for API key index {i} (key ending ...{key[-4:] if len(key) >=4 else 'key_too_short'}).")
            except Exception as e:
                self.logger.error(f"Failed to initialize client for API key index {i} (key ending ...{key[-4:] if len(key) >=4 else 'key_too_short'}). Error: {str(e)}")
                self.clients[i] = None # Mark as unusable
        
        if not self.api_keys: # Should be caught by the initial check, but as a safeguard
             raise ValueError("No Google API keys provided")

        if all(c is None for c in self.clients.values()):
            self.logger.critical("All API keys failed to initialize. Please check API key validity and SDK configuration.")
            raise ValueError("All API keys failed to initialize. Please check API key validity and SDK configuration.")
    
    def _get_current_client(self):
        """Get the current Gemini client, finding a usable one if the current one failed to initialize."""
        client = self.clients.get(self.current_key_index)
        
        if client is None:
            current_key_display = "unknown_key"
            if self.current_key_index < len(self.api_keys): # Check if index is valid before accessing api_keys
                 key_val = self.api_keys[self.current_key_index]
                 current_key_display = f"...{key_val[-4:]}" if len(key_val) >= 4 else "key_too_short"

            self.logger.error(f"Client for API key index {self.current_key_index} (key {current_key_display}) is not available (it may have failed to initialize).")
            original_key_index = self.current_key_index
            
            # Attempt to find the next available client
            while client is None:
                self.logger.warning(f"Attempting to rotate to find a usable client, starting from index {self.current_key_index}.")
                self._rotate_key() # This changes self.current_key_index
                client = self.clients.get(self.current_key_index)
                
                # Check if we've looped through all keys and found no usable one
                if self.current_key_index == original_key_index: # No 'and client is None' needed here, if client was found, loop would break
                    if client is None: # This means after a full loop, the original_key_index (which is now current) is still None
                        self.logger.critical("No usable API clients available after checking all keys. All keys may have failed initialization or are currently unusable.")
                        raise RuntimeError("All API keys are currently unusable. Check logs for initialization errors.")
                
                if client is not None:
                    new_key_val = self.api_keys[self.current_key_index]
                    new_key_display = f"...{new_key_val[-4:]}" if len(new_key_val) >= 4 else "key_too_short"
                    self.logger.info(f"Switched to usable client at new index {self.current_key_index} (key {new_key_display}).")
                    break # Found a working client
            
            # If client is still None here, it means the loop failed.
            # The RuntimeError above should catch this, but as a safeguard:
            if client is None:
                 # This state should ideally be prevented by the check within the loop.
                 self.logger.critical(f"Critical: Could not find any usable client after attempting rotation. Last attempted index: {self.current_key_index}")
                 raise RuntimeError(f"Critical: Could not find any usable client. Last attempted index: {self.current_key_index}")
        
        return client
    
    def _rotate_key(self):
        """Rotate to the next API key"""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        # self.logger.info(f"Rotated to Google API key index: {self.current_key_index}") # Logging moved to execute_with_retry
        
    def execute_with_retry(self, operation_func, *args, **kwargs):
        """Execute a Gemini API operation with retry logic for server errors and key rotation for quota errors."""
        retries = 0 # Key rotation retries
        last_error = None
        
        # Define server error exception types to catch, if google_exceptions is available
        server_error_types = tuple()
        if google_exceptions:
            server_error_types = (google_exceptions.InternalServerError, google_exceptions.ServiceUnavailable)
        
        while retries <= self.max_retries:
            client = self._get_current_client()
            current_key_short = self.api_keys[self.current_key_index][-4:]
            self.logger.info(f"Using API key index: {self.current_key_index} (...{current_key_short})")
            
            # Assuming client.models.operation_func is how genai.Client works based on existing code
            operation_to_execute = getattr(client.models, operation_func)

            for attempt in range(2): # 0 for initial, 1 for server error retry
                try:
                    self.total_api_calls += 1
                    result = operation_to_execute(*args, **kwargs)
                    if result is None:
                        # This was an existing check, keep it.
                        self.logger.error(f"Received None response from Gemini API with key ...{current_key_short} on attempt {attempt + 1}")
                        # Not incrementing successful_api_calls here as result is None
                        raise ValueError("Received None response from Gemini API")
                    self.successful_api_calls += 1
                    self.logger.info(f"Successfully executed {operation_func} with key ...{current_key_short} on attempt {attempt + 1}")
                    return result # Success
                
                except Exception as e: # Catch all exceptions to determine retry strategy
                    last_error = e
                    error_msg = str(e) # Keep original case for logging, use .lower() for matching
                    
                    # Check for specific server errors if types are available
                    is_server_error = False
                    if server_error_types and isinstance(e, server_error_types):
                        is_server_error = True

                    if is_server_error:
                        self.logger.warning(f"Gemini API server error ({type(e).__name__}) for key ...{current_key_short} on attempt {attempt + 1}. Error: {error_msg}")
                        if attempt == 0: # First attempt for this key
                            self.server_error_retries += 1
                            self.logger.info(f"Waiting 3 seconds before retrying on the same key (...{current_key_short}).")
                            time.sleep(3)
                            # Loop continues for the second attempt
                        else: # Second attempt (retry) also failed
                            self.logger.error(f"Gemini API server error persisted after retry for key ...{current_key_short}.")
                            # Re-raise to be caught by the generic 'except Exception as e' logic below,
                            # which will then decide on key rotation.
                            raise
                    else: # Not a server error caught by specific types, or google_exceptions not available
                        # Check for quota errors (as per existing logic)
                        is_quota_error_type = any(term in error_msg.lower() for term in [
                            "quota exceeded", "rate limit", "resource exhausted",
                            "too many requests", "resource has been exhausted"
                        ])

                        if is_quota_error_type:
                            self.logger.warning(f"API limit error for key ...{current_key_short}. Error: {error_msg}. Rotating key.")
                            self.quota_error_retries += 1
                            # Break from inner 'attempt' loop to go to key rotation logic
                            break # This break exits the inner for-loop (attempts on current key)
                        else:
                            # For other errors (not server error, not quota error), don't retry with new key
                            self.logger.error(f"Non-retriable/non-quota error for key ...{current_key_short}: {error_msg} (Type: {type(e).__name__})")
                            raise # Re-raise the original error to be returned by execute_with_retry
            
            # This part is reached if:
            # 1. Inner loop 'break' due to quota error (is_quota_error_type will be True)
            # 2. Inner loop completed two attempts for server error, and the second one re-raised (last_error is a server error)
            
            # Determine if we need to rotate key
            # This logic is now after the inner attempt loop.
            # 'last_error' holds the relevant error from the inner loop.
            error_msg_for_rotation_check = str(last_error).lower()
            
            is_quota_error_for_rotation = any(term in error_msg_for_rotation_check for term in [
                "quota exceeded", "rate limit", "resource exhausted",
                "too many requests", "resource has been exhausted"
            ])
            
            # Also consider persistent server error (failed both attempts on a key) as a reason to rotate
            is_persistent_server_error = False
            if server_error_types and isinstance(last_error, server_error_types) and attempt == 1: # attempt == 1 means second try failed
                 is_persistent_server_error = True

            if is_quota_error_for_rotation or is_persistent_server_error:
                if retries < self.max_retries:
                    self._rotate_key()
                    retries += 1
                    self.logger.info(f"Rotated to Google API key index: {self.current_key_index} (...{self.api_keys[self.current_key_index][-4:]}). Key rotation attempt {retries}/{self.max_retries}.")
                    # Continue to the next iteration of the outer 'while' loop (try with new key)
                else:
                    self.logger.error(f"All API keys ({self.max_retries + 1} keys including initial) tried. Last error on key ...{current_key_short}: {str(last_error)}")
                    raise last_error # All keys exhausted
            else:
                # This case should ideally not be reached if non-quota/non-server errors are re-raised immediately.
                # If it is, it means an error wasn't properly categorized.
                self.logger.error(f"Exiting retry logic due to unhandled error case. Last error: {str(last_error)}")
                raise last_error

        # After the while loop, if no result has been returned, it means all retries failed.
        self.logger.error(f"Execute_with_retry failed after {retries} key rotations. Last error: {str(last_error)}")
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

    def get_internal_stats(self):
        return {
            "total_api_calls_attempted": self.total_api_calls,
            "successful_api_calls": self.successful_api_calls,
            "server_error_retries": self.server_error_retries,
            "quota_error_key_rotations": self.quota_error_retries, 
        }
