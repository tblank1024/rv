#!/bin/bash
# Attach this terminal to the RV-Manager tmux session.
#
#   ./attach-rv-manager.sh            # attach to 'rv-manager'
#   ./attach-rv-manager.sh <name>     # attach to another session name
#
# That session holds the RV-Manager Claude process (started at boot by the
# systemd --user unit rv-manager.service: a detached `tmux new-session -A -d -s
# rv-manager ... claude --continue ...`). Attaching lets you watch and type into
# it. To leave WITHOUT killing it, detach with the tmux prefix then d
# (default: Ctrl-b d) -- do NOT Ctrl-c or exit the shell, that would end the
# Claude session.
#
# If the session is not running, this starts it through its systemd unit (which
# waits for a default route, then runs `claude --continue`), rather than a bare
# `tmux new-session`, so it comes up the same way it does at boot.
set -u

SESSION="${1:-rv-manager}"
UNIT="rv-manager.service"

command -v tmux >/dev/null 2>&1 || { echo "tmux is not installed" >&2; exit 1; }

attach() {
    # Already inside tmux? Switch the current client instead of nesting.
    if [ -n "${TMUX:-}" ]; then
        exec tmux switch-client -t "$SESSION"
    fi
    exec tmux attach-session -t "$SESSION"
}

if tmux has-session -t "$SESSION" 2>/dev/null; then
    attach
fi

# Not running. Only auto-start the known RV-Manager session via its unit; for
# any other name, we do not know how to start it, so just report.
if [ "$SESSION" != "rv-manager" ]; then
    echo "No tmux session '$SESSION'. Running sessions:" >&2
    tmux ls 2>/dev/null | sed 's/^/  /' >&2 || echo "  (none)" >&2
    exit 1
fi

echo "rv-manager tmux session is not running; starting it via systemd --user..."
if ! systemctl --user start "$UNIT"; then
    echo "Could not start $UNIT. Try: systemctl --user status $UNIT" >&2
    exit 1
fi

for _ in $(seq 1 60); do           # the unit waits up to ~120s for a route
    tmux has-session -t "$SESSION" 2>/dev/null && break
    sleep 2
done

if tmux has-session -t "$SESSION" 2>/dev/null; then
    attach
fi
echo "Started $UNIT but the '$SESSION' session has not appeared yet." >&2
echo "Check: systemctl --user status $UNIT ; journalctl --user -u $UNIT -n 30" >&2
exit 1
