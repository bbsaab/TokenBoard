#!/usr/bin/env python3
"""
Quick start script for TokenBoard.
Run this directly without Docker: python run.py
"""

import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.main import app

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("Starting TokenBoard...")
    print("Dashboard: http://localhost:8080")
    print("Press Ctrl+C to stop")
    print("=" * 50 + "\n")

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True,
        use_reloader=False  # Disable reloader to prevent double init
    )
