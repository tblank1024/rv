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

# --- Stable GPIO chip symlink ---------------------------------------------
# The Pi 5's onboard header GPIO chip (driver "pinctrl-rp1") does not have a
# fixed /dev/gpiochipN number -- it has drifted across reboots/kernel
# updates on Sophie (seen as 4, 0, and 15). docker-compose.yml's alarm and
# webserver services bind to /dev/gpiochip-rp1, a udev-created symlink that
# always points at whichever chip currently has the pinctrl-rp1 driver, so
# they don't need to track the raw number.
#
# Needs an interactive terminal (sudo password).
echo ""
echo "=== Installing stable udev symlink for the RP1 GPIO chip ==="
sudo tee /etc/udev/rules.d/99-rp1-gpiochip.rules > /dev/null <<'RULE'
# Stable symlink for the Pi 5's onboard header GPIO chip (pinctrl-rp1).
# The chip number drifts across reboots/kernel updates (seen as 4, 0, 15
# on this host) -- containers/services should bind to /dev/gpiochip-rp1
# instead of a raw gpiochipN path.
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", DRIVERS=="pinctrl-rp1", SYMLINK+="gpiochip-rp1"
RULE

sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=gpio

echo "Verifying symlink:"
ls -l /dev/gpiochip-rp1

# Clean up placeholder directories Docker creates at /dev/gpiochipN when a
# bind-mount's source path doesn't exist at container-start time (an old
# docker-compose.yml bound gpiochip0/gpiochip4 directly, before the stable
# symlink existed). Harmless no-op once nothing references those paths.
for p in /dev/gpiochip0 /dev/gpiochip4; do
  if [[ -d "$p" && ! -L "$p" ]]; then
    sudo rmdir "$p" 2>/dev/null && echo "removed stray placeholder $p"
  fi
done

echo "Done. docker-compose.yml's alarm/webserver services can now be"
echo "(re)started -- they bind /dev/gpiochip-rp1, not a raw gpiochipN path."
