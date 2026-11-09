"""Compatibility import for the packaged OAuth provider."""

import sys

from appflowy_mcp import google_oauth as implementation

sys.modules[__name__] = implementation
