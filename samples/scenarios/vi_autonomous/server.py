#!/usr/bin/env python3
"""VI-ARS server for autonomous mode scenario."""
import uvicorn
from vi.server.server import create_app

app = create_app(db_path=":memory:")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
