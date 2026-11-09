"""Deterministic configuration for offline tests, including selected-file runs."""

import os

os.environ.setdefault("APPFLOWY_TOOL_PROFILE", "legacy")
os.environ.setdefault("MCP_SECRET_TOKEN", "test-secret-123")
os.environ.setdefault("ALLOWED_WORKSPACE_IDS", "ws-allowed")
os.environ.setdefault("MCP_ALLOWED_HOSTS", "testserver")
