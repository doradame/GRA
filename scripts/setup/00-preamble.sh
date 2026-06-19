#!/usr/bin/env bash
# Welcome banner and initial information.
# shellcheck shell=bash source-path=SCRIPTDIR

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"

run_preamble() {
    clear 2>/dev/null || true
    log_banner "Graph RAG Assistant - Installer VPS"
    log_info "Questo script configura l'intero stack su un VPS Ubuntu 22.04/24.04 LTS."
    log_info "Docker e Docker Compose devono essere gia' installati."
    echo
}
