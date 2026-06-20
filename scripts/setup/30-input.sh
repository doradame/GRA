#!/usr/bin/env bash
# Collect domain, API keys, email, and admin credentials from the user.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib/prompts.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib/validators.sh"

run_input() {
    log_step "30" "Raccolta configurazione"

    while true; do
        ask_required "Dominio root (es. example.com)" "DOMAIN_ROOT"
        if is_valid_domain "$DOMAIN_ROOT"; then break; fi
        log_error "Dominio non valido."
    done

    DOMAIN_ADMIN="admin.${DOMAIN_ROOT}"
    DOMAIN_API="api.${DOMAIN_ROOT}"
    DOMAIN_CHAT="chat.${DOMAIN_ROOT}"
    DOMAIN_CHAT_ADMIN="chat-admin.${DOMAIN_ROOT}"
    DOMAIN_MCP="mcp.${DOMAIN_ROOT}"

    log_info "Sottodomini configurati:"
    log_info "  Admin:      $DOMAIN_ADMIN"
    log_info "  API:        $DOMAIN_API"
    log_info "  Chat:       $DOMAIN_CHAT"
    log_info "  Chat Admin: $DOMAIN_CHAT_ADMIN"
    log_info "  MCP:        $DOMAIN_MCP"

    local host_ip_input
    read -rp "IP su cui bindare le porte pubbliche (80/443) [0.0.0.0]: " host_ip_input
    HOST_IP=${host_ip_input:-0.0.0.0}
    log_info "IP bind porte:       $HOST_IP"

    while true; do
        ask_required "OpenAI API Key" "OPENAI_API_KEY"
        if is_valid_openai_key "$OPENAI_API_KEY"; then break; fi
        log_error "API key non valida."
    done

    while true; do
        ask_required "Resend API Key" "RESEND_API_KEY"
        if is_valid_resend_key "$RESEND_API_KEY"; then break; fi
        log_error "API key non valida."
    done

    while true; do
        ask_required "Indirizzo mittente email" "EMAIL_FROM"
        if is_valid_email "$EMAIL_FROM"; then break; fi
        log_error "Email non valida."
    done
    local name_input
    read -rp "Nome mittente [Graph RAG Assistant]: " name_input
    EMAIL_FROM_NAME=${name_input:-"Graph RAG Assistant"}

    while true; do
        ask_required "Email admin backend" "ADMIN_BACKEND_EMAIL"
        if is_valid_email "$ADMIN_BACKEND_EMAIL"; then break; fi
        log_error "Email non valida."
    done
    ask_password "Password admin backend" "ADMIN_BACKEND_PASSWORD"

    while true; do
        ask_required "Email admin LibreChat" "ADMIN_LIBRECHAT_EMAIL"
        if is_valid_email "$ADMIN_LIBRECHAT_EMAIL"; then break; fi
        log_error "Email non valida."
    done
    ask_password "Password admin LibreChat" "ADMIN_LIBRECHAT_PASSWORD"

    echo
    log_banner "Riepilogo"
    log_info "Dominio root:        $DOMAIN_ROOT"
    log_info "  Admin panel:       $DOMAIN_ADMIN"
    log_info "  API backend:       $DOMAIN_API"
    log_info "  LibreChat:         $DOMAIN_CHAT"
    log_info "  LibreChat Admin:   $DOMAIN_CHAT_ADMIN"
    log_info "  MCP Server:        $DOMAIN_MCP"
    log_info "IP bind porte:       $HOST_IP"
    log_info "OpenAI API Key:      fornita (${#OPENAI_API_KEY} caratteri)"
    log_info "Resend API Key:      fornita (${#RESEND_API_KEY} caratteri)"
    log_info "Email mittente:      $EMAIL_FROM_NAME <$EMAIL_FROM>"
    log_info "Admin backend:       $ADMIN_BACKEND_EMAIL"
    log_info "Admin LibreChat:     $ADMIN_LIBRECHAT_EMAIL"
    log_info "Password admin:      impostate"
    if ! ask_yes_no "Confermi di voler procedere?" "y"; then
        log_info "Setup annullato dall'utente."
        exit 0
    fi
}
