import os
import sys
import io

# Set UTF-8 encoding for standard output
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import uvicorn
from pathlib import Path

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import init_db

def main():
    print("============================================================")
    print("🚀 Starting RS AI Agent Platform...")
    print("============================================================")
    
    # Initialize DB
    try:
        init_db()
    except Exception as e:
        print(f"[DB Init Warning]: {e}")
    
    port = int(os.getenv("PORT", "10000"))
    host = os.getenv("HOST", "0.0.0.0")
    
    print(f"\n📍 Server listening on: http://{host}:{port}")
    print(f"🌐 Health endpoint available at: http://{host}:{port}/health")
    print("=" * 60 + "\n")
    
    uvicorn.run("app.main:app", host=host, port=port, reload=False, workers=1, access_log=True)

if __name__ == "__main__":
    main()
