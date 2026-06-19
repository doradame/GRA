#!/usr/bin/env bash
# Create persistent data directories.
# shellcheck shell=bash source-path=SCRIPTDIR
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/colors.sh"

if [[ ! -f "docker-compose.yml" ]]; then
    log_error "Esegui questo script dalla root del progetto Graph RAG Assistant."
    exit 1
fi

run_data_dirs() {
    log_step "60" "Creazione directory dati persistenti"
    mkdir -p data/{postgres,neo4j/{data,logs},qdrant,minio,caddy/{data,config},mongo,meilisearch,documents,huggingface}
    log_success "Directory dati create."
}
