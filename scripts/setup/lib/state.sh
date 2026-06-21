#!/usr/bin/env bash
# Installer state persistence helpers.
# shellcheck shell=bash source-path=SCRIPTDIR

STATE_FILE=".installer-state.env"

# _sq: quote a string for safe use inside single quotes.
_sq() {
    printf '%s' "$1" | sed "s/'/'\\\\''/g"
}

# _write_var: writes "NAME='value'" for the variable named $1 if it is set.
_write_var() {
    local var_name="$1"
    if [[ -n "${!var_name+x}" ]]; then
        printf "%s='%s'\n" "$var_name" "$(_sq "${!var_name}")"
    fi
}

# save_state: persists user input, generated secrets and the last completed step.
# Values are single-quoted so they survive sourcing safely, even with spaces,
# quotes or dollars. The state file is kept restrictive (chmod 600).
save_state() {
    local step="$1"
    {
        echo "# Graph RAG Assistant installer state"
        echo "# Generated automatically - do not edit manually"
        printf "INSTALLER_STEP='%s'\n" "$(_sq "$step")"
        _write_var DOMAIN_ROOT
        _write_var DOMAIN_ADMIN
        _write_var DOMAIN_API
        _write_var DOMAIN_CHAT
        _write_var DOMAIN_CHAT_ADMIN
        _write_var DOMAIN_MCP
        _write_var HOST_IP
        _write_var OPENAI_API_KEY
        _write_var RESEND_API_KEY
        _write_var EMAIL_FROM
        _write_var EMAIL_FROM_NAME
        _write_var ADMIN_BACKEND_EMAIL
        _write_var ADMIN_BACKEND_PASSWORD
        _write_var ADMIN_LIBRECHAT_EMAIL
        _write_var ADMIN_LIBRECHAT_PASSWORD
        _write_var SECRET_KEY
        _write_var MCP_API_KEY
        _write_var LIBRECHAT_BACKEND_API_KEY
        _write_var POSTGRES_PASSWORD
        _write_var NEO4J_PASSWORD
        _write_var MINIO_ACCESS_KEY
        _write_var MINIO_SECRET_KEY
        _write_var MEILI_MASTER_KEY
        _write_var JWT_SECRET
        _write_var JWT_REFRESH_SECRET
        _write_var CREDS_KEY
        _write_var CREDS_IV
        _write_var SESSION_SECRET
    } > "$STATE_FILE"
    chmod 600 "$STATE_FILE"
}

# load_state: sources the saved state file if it exists.
load_state() {
    if [[ -f "$STATE_FILE" ]]; then
        # shellcheck source=/dev/null
        source "$STATE_FILE"
    fi
}

# clear_state: removes the saved state file after successful completion.
clear_state() {
    if [[ -f "$STATE_FILE" ]]; then
        rm -f "$STATE_FILE"
    fi
}

# has_state: returns 0 if a saved state exists.
has_state() {
    [[ -f "$STATE_FILE" ]]
}
