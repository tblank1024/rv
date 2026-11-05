#!/bin/bash
# Durable weekly trigger: types the forward-the-report prompt into the RV-Manager tmux session.
# The systemd timer, not the session, holds the schedule, so it survives session restarts.
# Usage: nudge_rv_manager.sh [failed]   ("failed" = called from OnFailure= of the report unit)
set -u
D=/home/tblank/code/tblank1024/rv/reports/out
now=$(date +%s)
age() { echo $(( now - $(stat -c %Y "$1" 2>/dev/null || echo 0) )); }
if [ "${1:-}" = failed ]; then
  MSG="ALERT: the Sophie report job (sophie-weekly-report.service) FAILED. Run 'journalctl --user -u sophie-weekly-report -n 50', tell the laptop Manager via SendMessage, and fix it."
elif [ "$(age $D/latest.md)" -gt 129600 ] || [ "$(age $D/history.jsonl)" -gt 129600 ]; then
  MSG="ALERT: the Sophie weekly report is MISSING or STALE (latest.md or history.jsonl older than 36 h). Check 'systemctl --user status sophie-weekly-report.timer', run reports/weekly_health_report.py --force, then tell the laptop Manager via SendMessage that the reporting job was down."
else
  MSG="Weekly Sophie report is ready: read /home/tblank/code/tblank1024/rv/reports/out/latest.md and send a short summary (flags, restarts, hardening suggestions) to the laptop Manager with SendMessage. If Manager is offline, hold it and send when Manager is listed again."
fi
for i in $(seq 1 30); do tmux has-session -t rv-manager 2>/dev/null && break; sleep 10; done
tmux send-keys -t rv-manager -l "$MSG" && sleep 1 && tmux send-keys -t rv-manager Enter
