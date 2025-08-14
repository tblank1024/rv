#!/bin/bash
# Minimal setup for Raspberry Pi 5 - Install system packages only
# Python packages are handled by requirements.txt

echo "Installing system packages for Raspberry Pi 5 GPIO..."

# Update package list
sudo apt update

# Install libgpiod system packages (required for libgpiod pin factory)
sudo apt install -y libgpiod-dev python3-libgpiod gpiod

echo ""
echo "System setup complete!"
echo ""
echo "Now install Python packages with:"
echo "  pip3 install -r requirements.txt"
echo ""
echo "Then test with:"
echo "  python3 test_gpio.py"
