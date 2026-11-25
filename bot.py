"""Compatibility entry point; the application now lives in :mod:`app`."""

import asyncio

from app.main import main

if __name__ == "__main__":
    asyncio.run(main())
