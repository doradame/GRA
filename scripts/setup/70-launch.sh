#!/usr/bin/env bash
# Pull images and start the Docker stack.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib/prompts.sh"

run_launch() {
    log_step "70" "Avvio stack Docker"
    docker compose pull
    docker compose up -d

    log_info "Attesa avvio container..."
    sleep 10

    local max_attempts=30
    local attempt=0
    local running=0
    while [[ $attempt -lt $max_attempts ]]; do
        running=$(docker compose ps --services --filter status=running 2>/dev/null | wc -l)
        if [[ $running -ge 1 ]]; then
            log_success "Container avviati."
            return
        fi
        attempt=$((attempt + 1))
        sleep 5
    done

    log_warn "Timeout nell'attesa dei container. Controlla i log:"
    docker compose logs --tail 50 backend caddy || true
    if ask_yes_no "Vuoi continuare comunque?" "n"; then
        return
    fi
    exit 1
}
