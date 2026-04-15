import sys
import os
from pathlib import Path

# Vercel deployment: triggered fresh build on 2026-04-15
# Add backend to path for imports
backend_dir = Path(__file__).parent.parent / "taxai" / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Now import the FastAPI app
from app.main import app


