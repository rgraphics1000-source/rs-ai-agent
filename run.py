import os
import sys
import io

# Set UTF-8 encoding for Windows standard output
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import uvicorn
from pathlib import Path

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import init_db

def main():
    print("============================================================")
    print("🚀 Starting RS AI Agent Platform (100% Free)...")
    print("============================================================")

    # Initialize DB
    init_db()

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"\n📍 Server running at: http://{host}:{port}")
    print(f"🌐 Open http://localhost:{port} in your browser to access the Admin Dashboard.")
    print("=" * 60 + "\n")

    uvicorn.run("app.main:app", host=host, port=port, reload=False)

if __name__ == "__main__":
    main()
