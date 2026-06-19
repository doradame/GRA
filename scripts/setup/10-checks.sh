#!/usr/bin/env bash
# Verify required tools: docker, docker compose, git, curl, openssl.
# shellcheck shell=bash source-path=SCRIPTDIR

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"

check_command() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log_error "Comando richiesto non trovato: $cmd"
        log_error "Installa $cmd e riprova."
        exit 1
    fi
}

check_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        source /etc/os-release
        if [[ "$ID" != "ubuntu" || ("$VERSION_ID" != "22.04" && "$VERSION_ID" != "24.04") ]]; then
            log_warn "Sistema operativo rilevato: $ID $VERSION_ID."
            log_warn "Questo installer e' ottimizzato per Ubuntu 22.04/24.04 LTS."
        fi
    else
        log_warn "Impossibile rilevare il sistema operativo."
    fi
}

run_checks() {
    log_step "10" "Verifica prerequisiti"
    check_os
    check_command docker
    if ! docker compose version >/dev/null 2>&1; then
        log_error "Docker Compose plugin non trovato."
        exit 1
    fi
    check_command git
    check_command curl
    check_command openssl
    log_success "Tutti i prerequisiti sono soddisfatti."
}
