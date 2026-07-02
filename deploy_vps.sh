#!/bin/bash
set -euo pipefail

echo "=========================================="
echo "🚀 AppFlowy MCP Server — VPS deploy"
echo "=========================================="

# Run from the repo root (next to docker-compose.yaml).
cd "$(dirname "$0")"

read -r -p "Bot AppFlowy email: " APPFLOWY_EMAIL
read -r -s -p "Bot AppFlowy password: " APPFLOWY_PASSWORD; echo
read -r -p "Allowed workspace id(s), comma-separated: " ALLOWED_WORKSPACE_IDS
read -r -p "Public host (e.g. mcp.example.com): " MCP_HOST

MCP_SECRET_TOKEN=$(openssl rand -hex 32)

# Write .env with tight permissions (holds the bot password).
umask 077
cat > .env <<EOF
APPFLOWY_EMAIL="${APPFLOWY_EMAIL}"
APPFLOWY_PASSWORD="${APPFLOWY_PASSWORD}"
MCP_SECRET_TOKEN="${MCP_SECRET_TOKEN}"
ALLOWED_WORKSPACE_IDS="${ALLOWED_WORKSPACE_IDS}"
MCP_HOST="${MCP_HOST}"
MCP_ALLOWED_HOSTS="${MCP_HOST}"
MCP_ALLOWED_ORIGINS="https://${MCP_HOST}"
EOF
chmod 600 .env

echo "Building and deploying..."
docker compose up -d --build

echo "=========================================="
echo "✅ Deployed. Client config (Streamable HTTP, header auth):"
echo "=========================================="
cat <<EOF
{
  "mcpServers": {
    "appflowy": {
      "url": "https://${MCP_HOST}/mcp",
      "headers": { "Authorization": "Bearer ${MCP_SECRET_TOKEN}" }
    }
  }
}
EOF
echo
echo "Keep MCP_SECRET_TOKEN secret (never in a URL). For real privacy, put the"
echo "endpoint behind a Cloudflare Tunnel + Access so the port is never public."
