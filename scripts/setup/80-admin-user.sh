#!/usr/bin/env bash
# Create admin users for the backend and provide LibreChat admin instructions.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"

create_backend_admin() {
    local api_url="https://${DOMAIN_API}/api/v1/auth/register"

    local health_url="https://${DOMAIN_API}/api/v1/health"
    log_info "Attesa disponibilita' backend su $health_url..."
    local max_attempts=24
    local attempt=0
    local healthy=0
    while [[ $attempt -lt $max_attempts ]]; do
        if curl -sf "$health_url" >/dev/null 2>&1; then
            healthy=1
            break
        fi
        attempt=$((attempt + 1))
        sleep 5
    done
    if [[ "$healthy" -ne 1 ]]; then
        log_warn "Backend non risponde dopo 2 minuti."
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
