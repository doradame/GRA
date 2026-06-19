#!/usr/bin/env bash
# shellcheck shell=bash source-path=SCRIPTDIR

# shellcheck source=colors.sh
source "$(dirname "${BASH_SOURCE[0]}")/colors.sh"

# ask_required: reads a mandatory string value from the user.
# Arguments:
#   $1 - prompt message to display
#   $2 - name of the variable where the answer will be stored
ask_required() {
    local prompt="$1"
    local var_name="$2"
    local value=""
    while [[ -z "$value" ]]; do
        read -rp "$prompt: " value
        if [[ -z "$value" ]]; then
            log_error "Valore obbligatorio."
        fi
    done
    printf -v "$var_name" '%s' "$value"
}

# ask_password: reads and confirms a password (minimum 12 characters) without echoing input.
# Arguments:
#   $1 - prompt message to display
#   $2 - name of the variable where the password will be stored
ask_password() {
    local prompt="$1"
    local var_name="$2"
    local password=""
    local confirm=""
    local original_stty

    original_stty=$(stty -g)
    # shellcheck disable=SC2317
    restore_echo() { stty "$original_stty"; }
    trap restore_echo INT TERM EXIT

    while true; do
        read -rsp "$prompt: " password
        echo
        read -rsp "Conferma $prompt: " confirm
        echo
        if [[ "$password" != "$confirm" ]]; then
            log_error "Le password non coincidono. Riprova."
        elif [[ ${#password} -lt 12 ]]; then
            log_error "La password deve essere di almeno 12 caratteri."
        else
            break
        fi
    done

    trap - INT TERM EXIT
    printf -v "$var_name" '%s' "$password"
}

# ask_yes_no: asks the user a yes/no question.
# Arguments:
#   $1 - prompt message to display
#   $2 - default answer (y/n); defaults to "y" if omitted
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
            *) log_warn "Rispondi y o n." ;;
        esac
    done
}
