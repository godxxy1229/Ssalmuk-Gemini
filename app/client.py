"""
Centralized module for Gemini client instance
This solves circular import issues by providing a single source of truth
"""
import os
import logging
from typing import List

try:
    from google import genai
except ImportError:
    try:
        import google.genai as genai
    except ImportError:
        raise ImportError(
            "Failed to import Google Genai SDK. Please install it with: pip install google-genai"
        )

from app.gemini_client import GeminiClient

# Setup logging
logger = logging.getLogger(__name__)

# Get environment variables
GOOGLE_API_KEYS = os.getenv("GOOGLE_API_KEYS", "").split(",")
if not GOOGLE_API_KEYS or not GOOGLE_API_KEYS[0]:
    logger.warning("GOOGLE_API_KEYS environment variable not set or empty. Using dummy key.")
    GOOGLE_API_KEYS = ["dummy_key_for_testing"]  # Fallback for initial testing

# Create Gemini client (singleton to be imported by other modules)
gemini_client = GeminiClient(api_keys=GOOGLE_API_KEYS)
