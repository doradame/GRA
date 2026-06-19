#!/usr/bin/env bash
# Main entry point for the Graph RAG Assistant VPS installer.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_DIR="$SCRIPT_DIR/setup"

PROJECT_DIR=""

source "$SETUP_DIR/lib/colors.sh"
source "$SETUP_DIR/lib/prompts.sh"

trap 'log_error "Setup interrotto al passo ${CURRENT_STEP:-iniziale}."; exit 1' ERR

load_module() {
    local module="$1"
    source "$SETUP_DIR/$module"
}

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

CURRENT_STEP="30"
load_module "30-input.sh"
run_input

CURRENT_STEP="40"
load_module "40-secrets.sh"
run_secrets

CURRENT_STEP="50"
load_module "50-config.sh"
run_config

CURRENT_STEP="60"
load_module "60-data.sh"
run_data_dirs

CURRENT_STEP="70"
load_module "70-launch.sh"
run_launch

CURRENT_STEP="80"
load_module "80-admin-user.sh"
run_admin_users

CURRENT_STEP="99"
load_module "99-summary.sh"
run_summary

log_success "Setup completato con successo."
