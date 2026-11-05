#!/bin/bash
# Durable weekly trigger: types the forward-the-report prompt into the RV-Manager tmux session.
# Survives session restarts (the systemd timer, not the session, holds the schedule).
set -u
MSG="Weekly Sophie report is ready: read /home/tblank/code/tblank1024/rv/reports/out/latest.md and send a short summary (flags, restarts, hardening suggestions) to the laptop Manager with SendMessage. Skip if Manager is offline and retry next time Manager is listed."
for i in $(seq 1 30); do tmux has-session -t rv-manager 2>/dev/null && break; sleep 10; done
tmux send-keys -t rv-manager -l "$MSG" && sleep 1 && tmux send-keys -t rv-manager Enter
