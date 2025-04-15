#!/usr/bin/env python3
import sys
import os
import argparse

# Add parent directory to path to import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.api_key_manager import create_api_keys
from app.models import ApiKey
from app.database import SessionLocal

def main():
    parser = argparse.ArgumentParser(description="Generate API keys for Gemini API proxy")
    parser.add_argument("--count", type=int, default=100, help="Number of API keys to generate")
    parser.add_argument("--output", type=str, help="Output file to save generated keys")
    args = parser.parse_args()
    
    # Generate keys
    print(f"Generating {args.count} API keys...")
    new_keys = create_api_keys(args.count)
    
    # Get all keys from database
    db = SessionLocal()
    if not new_keys:
        # If no new keys were created, get all active keys
        keys = [k.key for k in db.query(ApiKey).filter(ApiKey.active == True).all()]
    else:
        keys = new_keys
    db.close()
    
    # Print and/or save keys
    print(f"Total keys available: {len(keys)}")
    
    if args.output:
        with open(args.output, "w") as f:
            for key in keys:
                f.write(f"{key}\n")
        print(f"Saved keys to {args.output}")
    else:
        print("API Keys:")
        for key in keys:
            print(key)

if __name__ == "__main__":
    main()