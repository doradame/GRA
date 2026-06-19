#!/usr/bin/env bash
set -euo pipefail

RESET='\033[0m'
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'

info() { echo -e "${BLUE}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*" >&2; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
step() { echo -e "${CYAN}[STEP $1]${RESET} $2"; }
banner() { echo -e "${BOLD}$*${RESET}"; }
