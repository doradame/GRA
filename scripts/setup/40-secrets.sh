#!/usr/bin/env bash
# Generate internal secrets for the stack services.
# shellcheck shell=bash source-path=SCRIPTDIR

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"

generate_secret() {
    openssl rand -hex 32
}

run_secrets() {
    log_step "40" "Generazione secret interni"

    SECRET_KEY="$(generate_secret)"
    MCP_API_KEY="$(generate_secret)"
    LIBRECHAT_BACKEND_API_KEY="$(generate_secret)"
    POSTGRES_PASSWORD="$(generate_secret)"
    NEO4J_PASSWORD="$(generate_secret)"
    MINIO_ACCESS_KEY="$(generate_secret | cut -c1-20)"
    MINIO_SECRET_KEY="$(generate_secret)"
    MEILI_MASTER_KEY="$(generate_secret)"
    JWT_SECRET="$(generate_secret)"
    JWT_REFRESH_SECRET="$(generate_secret)"
    CREDS_KEY="$(generate_secret)"
    CREDS_IV="$(openssl rand -hex 16)"
    SESSION_SECRET="$(generate_secret)"

    log_success "Secret interni generati."
}
