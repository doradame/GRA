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

run_checks() {
    log_step "10" "Verifica prerequisiti"
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
