from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from sqlalchemy.orm import Session
import time
import asyncio

from app.database import engine, get_db
from app.models import Base, ApiKey
from app.api_key_manager import create_api_keys
# Import the client separately (no circular dependency)
from app.client import gemini_client
from app.routers import generate, embed, admin, files
from app.queue_manager import queue_manager  # Import the queue manager
# Add this import for get_api_key
from app.utils.security import get_api_key

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create tables
Base.metadata.create_all(bind=engine)

# Create FastAPI app
app = FastAPI(
    title="Gemini API Proxy",
    description="Custom API proxy for Google's Gemini API with API key management",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# Include routers
app.include_router(generate.router)
app.include_router(embed.router)
app.include_router(files.router)
app.include_router(admin.router)

@app.on_event("startup")
async def startup_event():
    """Run on startup - create API keys if needed and start queue manager"""
    logger.info("Starting Gemini API Proxy")
    
    # Create API keys if none exist
    db = next(get_db())
    key_count = db.query(ApiKey).count()
    
    if key_count < 100:
        logger.info(f"Creating {100 - key_count} API keys")
        created_keys = create_api_keys(100 - key_count)
        logger.info(f"Created {len(created_keys)} API keys")
    else:
        logger.info(f"Found {key_count} existing API keys")
    
    # Start the queue manager
    queue_manager.start_processing()
    logger.info("Queue manager started")

@app.on_event("shutdown")
async def shutdown_event():
    """Run on shutdown - stop queue manager"""
    logger.info("Stopping Gemini API Proxy")
    queue_manager.stop_processing()
    logger.info("Queue manager stopped")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Check queue status
    queue_size = queue_manager.queue.qsize()
    return {
        "status": "ok",
        "queue_size": queue_size
    }

@app.get("/queue-status")
async def queue_status(api_key: str = Depends(get_api_key)):
    """Get queue status (admin)"""
    queue_size = queue_manager.queue.qsize()
    return {
        "queue_size": queue_size,
        "active_requests_count": len(queue_manager.results)
    }

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Gemini API Proxy",
        "version": "1.0.0",
        "description": "Custom API proxy for Google's Gemini API with API key management",
    }

# Add script execution if needed
if __name__ == "__main__":
    import uvicorn
    import argparse
    from app.utils.port_utils import find_available_port
    
    parser = argparse.ArgumentParser(description="Run Gemini API Proxy")
    parser.add_argument("--port", type=int, default=None, help="Port to run the server on")
    args = parser.parse_args()
    
    port = args.port if args.port else find_available_port(8000, 9000)
    print(f"Starting server on port {port}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
