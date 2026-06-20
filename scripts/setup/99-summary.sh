#!/usr/bin/env bash
# Final summary displayed after successful setup.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"

run_summary() {
    log_step "99" "Riepilogo"
    echo
    log_banner "Graph RAG Assistant installato!"
    echo
    log_info "Pannello Admin:     https://${DOMAIN_ADMIN}"
    log_info "API Backend:        https://${DOMAIN_API}"
    log_info "LibreChat:          https://${DOMAIN_CHAT}"
    log_info "LibreChat Admin:    https://${DOMAIN_CHAT_ADMIN}"
    log_info "MCP Server:         https://${DOMAIN_MCP}/sse"
    echo
    log_info "Admin backend:      ${ADMIN_BACKEND_EMAIL}"
    log_info "Admin LibreChat:    ${ADMIN_LIBRECHAT_EMAIL}"
    echo
    log_info "Prossimi passi:"
    log_info "1. Verifica che i DNS puntino correttamente al VPS."
    log_info "2. Accedi al pannello admin e carica i tuoi documenti."
    log_info "3. Accedi a LibreChat e inizia a chattare con Graph RAG Assistant."
}
