#!/usr/bin/env bash
# Input validation helpers used by the VPS installer.
# shellcheck shell=bash source-path=SCRIPTDIR

is_valid_domain() {
    local domain="$1"
    [[ "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)+$ ]]
}

is_valid_email() {
    local email="$1"
    [[ "$email" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]
}

is_valid_openai_key() {
    local key="$1"
    [[ "$key" =~ ^sk-[a-zA-Z0-9_-]{20,}$ ]]
}

is_valid_resend_key() {
    local key="$1"
    [[ "$key" =~ ^re_[a-zA-Z0-9]{20,}$ ]]
}
