#!/usr/bin/env bash
# Create admin users for the backend and provide LibreChat admin instructions.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"

# _wait_for_backend: waits until the FastAPI docs endpoint responds.
# /docs is public and is a reliable signal that the backend is ready.
_wait_for_backend() {
    local docs_url="https://${DOMAIN_API}/docs"
    log_info "Attesa disponibilita' backend su $docs_url..."
    local max_attempts=60
    local attempt=0
    while [[ $attempt -lt $max_attempts ]]; do
        if curl -sf "$docs_url" >/dev/null 2>&1; then
            log_success "Backend disponibile."
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 5
    done
    log_warn "Backend non risponde dopo 5 minuti."
    return 1
}

create_backend_admin() {
    local api_url="https://${DOMAIN_API}/api/v1/auth/register"

    if ! _wait_for_backend; then
        log_warn "Crea l'utente manualmente da: https://${DOMAIN_ADMIN}"
        return
    fi

    log_info "Creazione admin backend su $api_url..."

    local response
    response=$(curl -s --max-time 30 -w "\\n%{http_code}" -X POST "$api_url" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${ADMIN_BACKEND_EMAIL}\",\"password\":\"${ADMIN_BACKEND_PASSWORD}\"}" || true)

    local http_code
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | sed '$d')

    if [[ -z "$http_code" ]]; then
        log_warn "Nessuna risposta dal backend durante la creazione dell'admin."
        log_warn "Crea l'utente manualmente da: https://${DOMAIN_ADMIN}"
        return
    fi

    if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
        log_success "Admin backend creato."
    elif echo "$body" | grep -qi "already registered\\|already exists\\|esiste già"; then
        log_warn "Utente backend esiste gia'."
    else
        log_warn "Creazione admin backend fallita (HTTP $http_code)."
        log_warn "Risposta: $body"
        log_warn "Crea l'utente manualmente da: https://${DOMAIN_ADMIN}"
    fi
}

create_librechat_admin() {
    log_info "Creazione admin LibreChat..."
    log_warn "La registrazione in LibreChat e' disabilitata per sicurezza."
    log_warn "Per creare il primo admin:"
    log_warn "1. Accedi temporaneamente abilitando ALLOW_REGISTRATION=true"
    log_warn "2. Registra ${ADMIN_LIBRECHAT_EMAIL} su https://${DOMAIN_CHAT}"
    log_warn "3. Disabilita nuovamente ALLOW_REGISTRATION"
}

run_admin_users() {
    log_step "80" "Creazione utenti admin"
    create_backend_admin
    create_librechat_admin
}
