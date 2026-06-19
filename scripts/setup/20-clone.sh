#!/usr/bin/env bash
# Detect existing project directory or clone the repository.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib/prompts.sh"

run_clone() {
    log_step "20" "Verifica repository"
    if [[ -f "$(pwd)/docker-compose.yml" && -f "$(pwd)/.env.example" ]]; then
        log_info "Rilevata cartella del progetto: $(pwd)"
        PROJECT_DIR="$(pwd)"
        return
    fi

    log_warn "Non sei dentro la cartella del progetto Graph RAG Assistant."
    if ask_yes_no "Vuoi clonare il repository?" "y"; then
        local repo_url
        ask_required "URL del repository Git" "repo_url"
        local target_dir
        read -rp "Cartella di destinazione [${HOME}/graph-rag-assistant]: " target_dir
        target_dir=${target_dir:-"${HOME}/graph-rag-assistant"}
        if [[ -z "$target_dir" ]]; then
            log_error "Cartella di destinazione non valida."
            exit 1
        fi
        if ! git clone "$repo_url" "$target_dir"; then
            log_error "Clonazione fallita."
            exit 1
        fi
        if ! cd "$target_dir"; then
            log_error "Impossibile entrare in $target_dir"
            exit 1
        fi
        PROJECT_DIR="$target_dir"
        log_success "Repository clonato in $target_dir"
    else
        log_error "Impossibile continuare senza il repository."
        exit 1
    fi
}
