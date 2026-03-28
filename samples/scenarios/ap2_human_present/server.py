#!/usr/bin/env python3
"""Start the AP2-ARS server with mock settlement."""

import uvicorn

from ap2.server.server import create_app

app = create_app(db_path=":memory:")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
