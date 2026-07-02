# Contributing to AppFlowy MCP Server

First off, thank you for considering contributing to the AppFlowy MCP Server! It's people like you that make open source such a great community.

## 💻 Development Setup

This project uses `uv` for lightning-fast Python dependency management.

1. **Install uv**: If you haven't already, install [uv](https://github.com/astral-sh/uv).
2. **Clone the repo**:
   ```bash
   git clone https://github.com/Rahulk644/appflowy-mcp-server.git
   cd appflowy-mcp-server
   ```
3. **Run the server locally**:
   ```bash
   uv run --with fastmcp --with httpx --with python-dotenv server.py
   ```

## ✅ Coding Standards

We enforce strict coding standards using `ruff`.

Before submitting a Pull Request, please run:
```bash
uv run --with ruff ruff format .
uv run --with ruff ruff check .
```

## 🚀 Pull Request Process

1. Fork the repository and create your branch from `main`.
2. Make your changes and ensure the code is properly formatted.
3. If you've added code that should be tested, add tests.
4. Update the README.md with details of changes to the interface, if applicable.
5. Submit your Pull Request!

## 🐛 Reporting Bugs

Bugs are tracked as GitHub issues. When creating an issue, please use the provided Bug Report template and provide as much detail as possible, including your OS, Python version, and a clear description of the problem.

## 💡 Proposing Features

Feature requests are welcome! Please use the Feature Request template when creating an issue.
