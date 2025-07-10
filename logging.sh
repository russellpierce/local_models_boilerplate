#!/bin/bash
# Mostly AI Authored, with additional prompts and modifications

# This script is used to log messages to the console in a consistent and readable format
# Logging utility script for GitLab CI pipelines
# Provides colored output functions for better visibility

# Color codes
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly PURPLE='\033[0;35m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m' # No Color

# Logging functions
print_red() {
    echo -e "${RED}$1${NC}"
}

print_green() {
    echo -e "${GREEN}$1${NC}"
}

print_yellow() {
    echo -e "${YELLOW}$1${NC}"
}

print_blue() {
    echo -e "${BLUE}$1${NC}"
}

print_purple() {
    echo -e "${PURPLE}$1${NC}"
}

print_cyan() {
    echo -e "${CYAN}$1${NC}"
}

# Log level functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${CYAN}[DEBUG]${NC} $1"
}

# Section header function
print_section() {
    local text="$1"
    local separator=$(printf '=%.0s' $(seq 1 ${#text}))
    echo
    echo -e "${PURPLE}==========================================${NC}"
    echo -e "${PURPLE}$text${NC}"
    echo -e "${PURPLE}$separator${NC}"
    echo
}

# Progress indicator
print_progress() {
    echo -e "${BLUE}[PROGRESS]${NC} $1"
}

# Command execution wrapper with logging
execute_with_log() {
    local cmd="$1"
    local description="$2"

    print_progress "Starting: $description"
    print_debug "Executing: $cmd"

    if eval "$cmd"; then
        log_success "Completed: $description"
    else
        log_error "Failed: $description"
        return 1
    fi
}