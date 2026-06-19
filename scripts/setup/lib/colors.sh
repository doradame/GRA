#!/usr/bin/env bash
# Logging helpers and ANSI color codes used by the VPS installer.
# shellcheck shell=bash source-path=SCRIPTDIR

C_RESET='\033[0m'
C_BOLD='\033[1m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_CYAN='\033[0;36m'

log_info() { echo -e "${C_BLUE}[INFO]${C_RESET} $*"; }
log_success() { echo -e "${C_GREEN}[OK]${C_RESET} $*"; }
log_warn() { echo -e "${C_YELLOW}[WARN]${C_RESET} $*" >&2; }
log_error() { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }
log_step() { echo -e "${C_CYAN}[STEP ${1:-}]${C_RESET} ${2:-}"; }
log_banner() { echo -e "${C_BOLD}$*${C_RESET}"; }
