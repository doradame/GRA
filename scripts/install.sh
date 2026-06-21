#!/usr/bin/env bash
# Main entry point for the Graph RAG Assistant VPS installer.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"

# Supporto per curl ... | bash: se lo script e' pipe-ato o i moduli non sono presenti, clona il repo.
if [[ -z "$SCRIPT_SOURCE" || "$SCRIPT_SOURCE" == "-" || ! -d "${SCRIPT_SOURCE%/*}/setup" ]]; then
    REPO_URL="${REPO_URL:-https://github.com/doradame/GRA.git}"
    TARGET_DIR="${HOME}/graph-rag-assistant"
    echo "[INFO] Moduli installer non trovati. Clonazione repository da $REPO_URL in $TARGET_DIR..."
    if [[ ! -d "$TARGET_DIR/.git" ]]; then
        git clone "$REPO_URL" "$TARGET_DIR"
    else
        echo "[INFO] Repository gia' presente in $TARGET_DIR."
    fi
    exec bash "$TARGET_DIR/scripts/install.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
SETUP_DIR="$SCRIPT_DIR/setup"

PROJECT_DIR=""

source "$SETUP_DIR/lib/colors.sh"
source "$SETUP_DIR/lib/prompts.sh"
source "$SETUP_DIR/lib/state.sh"

trap 'log_error "Setup interrotto al passo ${CURRENT_STEP:-iniziale}."; exit 1' ERR

load_module() {
    local module="$1"
    source "$SETUP_DIR/$module"
}

# Decide which steps to skip based on a previously saved state.
skip_input=false
skip_secrets=false
skip_config=false
skip_data=false
skip_launch=false
skip_admin=false

if has_state; then
    log_warn "Trovata configurazione precedente (ultimo step completato: ${INSTALLER_STEP:-inizio})."
    if ask_yes_no "Vuoi riprendere da dove eri rimasto?" "y"; then
        load_state
        case "${INSTALLER_STEP:-}" in
            input)
                skip_input=true
                ;;
            secrets)
                skip_input=true
                skip_secrets=true
                ;;
            config)
                skip_input=true
                skip_secrets=true
                skip_config=true
                ;;
            data)
                skip_input=true
                skip_secrets=true
                skip_config=true
                skip_data=true
                ;;
            launch)
                skip_input=true
                skip_secrets=true
                skip_config=true
                skip_data=true
                skip_launch=true
                ;;
            admin)
                skip_input=true
                skip_secrets=true
                skip_config=true
                skip_data=true
                skip_launch=true
                skip_admin=true
                ;;
        esac
    fi
fi

CURRENT_STEP="00"
load_module "00-preamble.sh"
run_preamble

CURRENT_STEP="10"
load_module "10-checks.sh"
run_checks

CURRENT_STEP="20"
load_module "20-clone.sh"
run_clone

cd "${PROJECT_DIR:-$(pwd)}"

if ! $skip_input; then
    CURRENT_STEP="30"
    load_module "30-input.sh"
    run_input
    save_state input
fi

if ! $skip_secrets; then
    CURRENT_STEP="40"
    load_module "40-secrets.sh"
    run_secrets
    save_state secrets
fi

if ! $skip_config; then
    CURRENT_STEP="50"
    load_module "50-config.sh"
    run_config
    save_state config
fi

if ! $skip_data; then
    CURRENT_STEP="60"
    load_module "60-data.sh"
    run_data_dirs
    save_state data
fi

if ! $skip_launch; then
    CURRENT_STEP="70"
    load_module "70-launch.sh"
    run_launch
    save_state launch
fi

if ! $skip_admin; then
    CURRENT_STEP="80"
    load_module "80-admin-user.sh"
    run_admin_users
    save_state admin
fi

CURRENT_STEP="99"
load_module "99-summary.sh"
run_summary

clear_state
log_success "Setup completato con successo."
