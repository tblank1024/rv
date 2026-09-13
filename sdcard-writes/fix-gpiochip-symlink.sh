#!/bin/bash
# One-time fix: install a stable udev symlink for the Pi 5's onboard header
# GPIO chip (pinctrl-rp1), and remove the stray placeholder directories
# Docker created at /dev/gpiochip0 and /dev/gpiochip4 when their old
# bind-mount sources went missing after a chip renumbering.
#
# Needs an interactive terminal (sudo password). Run directly on Sophie.

set -e

echo "--- Installing udev rule for stable RP1 GPIO chip symlink ---"
sudo tee /etc/udev/rules.d/99-rp1-gpiochip.rules > /dev/null <<'RULE'
# Stable symlink for the Pi 5's onboard header GPIO chip (pinctrl-rp1).
# The chip number drifts across reboots/kernel updates (seen as 4, 0, 15
# on this host) -- containers/services should bind to /dev/gpiochip-rp1
# instead of a raw gpiochipN path.
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", DRIVERS=="pinctrl-rp1", SYMLINK+="gpiochip-rp1"
RULE

sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=gpio

echo "--- Verifying symlink ---"
ls -l /dev/gpiochip-rp1

echo "--- Removing stray placeholder directories from the old bad bind-mount ---"
for p in /dev/gpiochip0 /dev/gpiochip4; do
  if [[ -d "$p" && ! -L "$p" ]]; then
    sudo rmdir "$p"
    echo "removed $p"
  else
    echo "skipping $p (not a plain directory, leaving it alone)"
  fi
done

echo "Done."
