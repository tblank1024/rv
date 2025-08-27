#!/bin/bash
# Simple function to run commands with sudo while preserving venv and directory
# Usage: sudo_with_venv "command to run"

function sudo_with_venv() {
    sudo bash -c "cd /home/tblank/code/tblank1024/rv/bat2mqtt && source venv/bin/activate && $1"
}

# Example usage:
# sudo_with_venv "DEBUG_LEVEL=1 python bat2mqtt_direct.py"
# sudo_with_venv "python --version"
