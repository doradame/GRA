#!/usr/bin/env bash
set -euo pipefail

# Simula variabili di input e secret, poi esegue run_config in una directory temporanea
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$(mktemp -d)"

# Crea struttura minimale
mkdir -p librechat lib

# Copia dipendenze necessarie per 50-config.sh
cp "$REPO_DIR/scripts/setup/lib/colors.sh" lib/
cp "$REPO_DIR/docker-compose.yml" .

# Variabili necessarie per 50-config.sh
DOMAIN_ROOT="example.com"
DOMAIN_ADMIN="admin.example.com"
DOMAIN_API="api.example.com"
DOMAIN_CHAT="chat.example.com"
DOMAIN_CHAT_ADMIN="chat-admin.example.com"
DOMAIN_MCP="mcp.example.com"
OPENAI_API_KEY="sk-test12345678901234567890123456789012"
RESEND_API_KEY="re_1234567890123456789012345"
EMAIL_FROM="noreply@example.com"
EMAIL_FROM_NAME="Graph RAG Assistant"
SECRET_KEY="secretsecretsecretsecretsecretsecretsecretsecret"
MCP_API_KEY="mcpmcpmcpmcpmcpmcpmcpmcpmcpmcpmcpmcpmcp"
LIBRECHAT_BACKEND_API_KEY="librechatlibrechatlibrechatlibrechatlibrechat"
POSTGRES_PASSWORD="postgrepasswordpostgrepasswordpostgrepassword"
NEO4J_PASSWORD="neo4jpasswordneo4jpasswordneo4jpassword"
MINIO_ACCESS_KEY="minioaccesskey12345"
MINIO_SECRET_KEY="miniosecretkeyminiosecretkeyminiosecretkey"
MEILI_MASTER_KEY="meilimasterkeymeilimasterkeymeilimasterkey"
JWT_SECRET="jwtsecretjwtsecretjwtsecretjwtsecretjwtsecret"
JWT_REFRESH_SECRET="jwtrefreshjwtrefreshjwtrefreshjwtrefreshjwt"
CREDS_KEY="credskeycredskeycredskeycredskeycredskeycredskeycreds"
CREDS_IV="credsivcredsivcredsiv"
SESSION_SECRET="sessionsecretsessionsecretsessionsecretsession"

# Copia modulo config dal repo
cp "$REPO_DIR/scripts/setup/50-config.sh" .

source ./50-config.sh
run_config

# Verifica file generati
for f in .env Caddyfile librechat/librechat.yaml librechat/librechat.env librechat/admin.env; do
    if [[ ! -f "$f" ]]; then
        echo "Missing file: $f"
        exit 1
    fi
done

echo "Config generation test passed."
