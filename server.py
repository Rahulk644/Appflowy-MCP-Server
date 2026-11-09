"""Compatibility entry point for ``python server.py`` and ``uvicorn server:app``."""

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=False)

if __name__ == "__main__":
    from appflowy_mcp.cli import main

    main()
else:
    # Keep existing imports and monkeypatches pointed at the implementation.
    from appflowy_mcp import server as implementation

    sys.modules[__name__] = implementation
