#!/usr/bin/env bash
# Pull images and start the Docker stack.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib/prompts.sh"

run_launch() {
    if [[ ! -f "docker-compose.yml" ]]; then
        log_error "Esegui questo script dalla root del progetto Graph RAG Assistant."
        exit 1
    fi
    log_step "70" "Avvio stack Docker"
    docker compose pull
    docker compose up -d

    log_info "Attesa avvio container..."
    sleep 10

    local max_attempts=30
    local attempt=0
    local expected
    expected=$(docker compose config --services 2>/dev/null | wc -l)
    local running=0
    while [[ $attempt -lt $max_attempts ]]; do
        running=$(docker compose ps --services --filter status=running 2>/dev/null | wc -l)
        if [[ "$running" -ge "$expected" && "$expected" -gt 0 ]]; then
            log_success "Container avviati ($running/$expected)."
            return
        fi
        attempt=$((attempt + 1))
        sleep 5
    done

    log_warn "Timeout nell'attesa dei container. Controlla i log:"
    docker compose logs --tail 50 backend caddy librechat librechat-admin || true
    if ask_yes_no "Vuoi continuare comunque?" "n"; then
        return
    fi
    exit 1
}
