#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/colors.sh"

ask_required() {
    local prompt="$1"
    local var_name="$2"
    local value=""
    while [[ -z "$value" ]]; do
        read -rp "$prompt: " value
        if [[ -z "$value" ]]; then
            error "Valore obbligatorio."
        fi
    done
    printf -v "$var_name" '%s' "$value"
}

ask_password() {
    local prompt="$1"
    local var_name="$2"
    local password=""
    local confirm=""
    while true; do
        read -rsp "$prompt: " password
        echo
        read -rsp "Conferma $prompt: " confirm
        echo
        if [[ "$password" != "$confirm" ]]; then
            error "Le password non coincidono. Riprova."
        elif [[ ${#password} -lt 12 ]]; then
            error "La password deve essere di almeno 12 caratteri."
        else
            break
        fi
    done
    printf -v "$var_name" '%s' "$password"
}

ask_yes_no() {
    local prompt="$1"
    local default="${2:-y}"
    local response
    while true; do
        read -rp "$prompt [${default}]: " response
        response=${response:-$default}
        case "$response" in
            [Yy]|[Yy][Ee][Ss]) return 0 ;;
            [Nn]|[Nn][Oo]) return 1 ;;
            *) warn "Rispondi y o n." ;;
        esac
    done
}
