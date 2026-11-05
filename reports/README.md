# Weekly report
`weekly_health_report.py [days]` — read-only restart + health report (reboots, container die/restart/oom/health events, host units, kernel undervoltage/OOM/IO/USB/CAN errors, disk/mem, WAN, MQTT SYS_ERRORS). Output: `out/latest.md` plus dated copies (newest 4 kept).
Scheduled by user timer `sophie-weekly-report.timer` (Mon 07:00; units live in `~/.config/systemd/user/`). `sophie-weekly-report-send.timer` (Mon 07:10) types a forward prompt into the `rv-manager` tmux session via `nudge_rv_manager.sh`; RV-Manager sends the summary to the laptop `Manager`.

Unit copies for reference in `systemd/`; install with `cp systemd/* ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now sophie-weekly-report.timer sophie-weekly-report-send.timer`.
