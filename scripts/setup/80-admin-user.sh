#!/usr/bin/env bash
# Create admin users for the backend and provide LibreChat admin instructions.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"

create_backend_admin() {
    local api_url="https://${DOMAIN_API}/api/v1/auth/register"
    log_info "Creazione admin backend su $api_url..."

    local response
    response=$(curl -s -w "\\n%{http_code}" -X POST "$api_url" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${ADMIN_BACKEND_EMAIL}\",\"password\":\"${ADMIN_BACKEND_PASSWORD}\"}" || true)

    local http_code
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | sed '$d')

    if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
        log_success "Admin backend creato."
    elif echo "$body" | grep -qi "already exists\\|esiste già"; then
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
