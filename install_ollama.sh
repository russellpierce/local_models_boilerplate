#!/bin/bash
# Initially AI Authored

# Source the logging script
source ./logging.sh
# Prompt for sudo password at the start and cache it
if ! sudo -v; then
    log_error "Sudo authentication failed. Exiting."
    exit 1
fi
# Keep sudo session alive while the script runs
( while true; do sudo -n true; sleep 60; done ) &
SUDO_KEEPALIVE_PID=$!
# The 'trap' command here ensures that when the script exits (for any reason), 
# the background process keeping the sudo session alive is killed to prevent it from running indefinitely.
trap 'kill $SUDO_KEEPALIVE_PID' EXIT

log_info "Starting Ollama installation script for Ubuntu 24.04..."

# Set environment variable for GPU RAM (in MB)
export GPU_RAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1)
log_info "Detected GPU RAM: ${GPU_RAM_MB} MB"

# Install prerequisites
log_info "Updating package lists..."
sudo apt-get update

log_info "Installing curl and required dependencies..."
sudo apt-get install -y curl

# Download and install Ollama
log_info "Installing Ollama using official installer..."
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama service
log_info "Starting Ollama service..."
sudo systemctl start ollama
sudo systemctl enable ollama

# Check if GPU RAM is at least 12GB (12288 MB)
if [ "$GPU_RAM_MB" -ge 12288 ]; then
    log_info "GPU RAM is sufficient (>=12GB). Installing recommended models..."
    ollama pull llama3
    ollama pull phi3
    log_info "Models 'llama3' and 'phi3' have been installed."
else
    log_warn "GPU RAM is less than 12GB. Skipping installation of large models."
fi

log_info "Ollama installation script completed."
