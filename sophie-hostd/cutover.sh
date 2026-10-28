#!/bin/bash
# cutover.sh -- drive the webserver de-privileging (sophie-hostd plan, steps 3-6)
# one step at a time. Your job at Sophie is just to run `./cutover.sh next` and
# read what it says; it does the work, verifies, and stops. If a step fails it
# does NOT advance, and the dangerous step (4) auto-rolls-back.
#
#   sudo ./cutover.sh            # status: where you are, what's next
#   sudo ./cutover.sh next       # do the next step, verify, stop
#   sudo ./cutover.sh verify     # re-run the current step's checks
#   sudo ./cutover.sh rollback   # undo everything, back to privileged webserver
#   sudo ./cutover.sh reset N    # force the step counter (recovery only)
#
# State lives in /var/lib so it survives the step-6 reboot. The compose and
# server.py edits are left in the working tree; commit them yourself once
# step 6 passes (the script tells you). Rollback is always `git checkout` +
# redeploy, so nothing here is one-way until you commit.
set -u

REPO="/home/tblank/code/tblank1024/rv"
COMPOSE="$REPO/docker/docker-compose.yml"
SERVER="$REPO/webserver/server/server.py"
STATE_DIR="/var/lib"
STATE="$STATE_DIR/sophie-cutover.state"
HOSTD="http://127.0.0.1:12348"
DASH="http://127.0.0.1:8000"
WS="webserver"

# Markers the server.py code work must carry, so step 4 never drops privilege
# before the dashboard can actually use hostd. These are grep'd, not written.
DUALPATH_MARK="sophie-hostd dual-path"      # present once step-3 code is committed
CLEANUP_MARK="sophie-hostd cutover complete" # present once step-5 code is committed

c_red=$'\e[31m'; c_grn=$'\e[32m'; c_yel=$'\e[33m'; c_dim=$'\e[2m'; c_off=$'\e[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s  ok %s %s\n' "$c_grn" "$c_off" "$*"; }
bad()  { printf '%s FAIL %s %s\n' "$c_red" "$c_off" "$*"; }
info() { printf '%s  -  %s%s\n' "$c_dim" "$*" "$c_off"; }

need_root() { [ "$(id -u)" -eq 0 ] || { bad "run with sudo"; exit 1; }; }
get_state() { [ -f "$STATE" ] && cat "$STATE" || echo 2; }   # 2 = daemon installed
set_state() { mkdir -p "$STATE_DIR"; echo "$1" >"$STATE"; }

# --- verification primitives -------------------------------------------------

v_hostd() {
  curl -fs --max-time 8 "$HOSTD/api/health" >/dev/null 2>&1 \
    && ok "sophie-hostd answers on 127.0.0.1:12348" || { bad "sophie-hostd not answering"; return 1; }
}
v_ws_healthy() {
  local h; h=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$WS" 2>/dev/null)
  [ "$h" = healthy ] && ok "webserver container healthy" || { bad "webserver health=$h"; return 1; }
}
v_dash() {
  local code; code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$DASH/health" 2>/dev/null)
  [ "$code" = 200 ] && ok "dashboard /health -> 200" || { bad "dashboard /health -> $code"; return 1; }
}
v_priv_dropped() {
  local p pid socks
  p=$(docker inspect -f '{{.HostConfig.Privileged}}' "$WS" 2>/dev/null)
  pid=$(docker inspect -f '{{.HostConfig.PidMode}}' "$WS" 2>/dev/null)
  socks=$(docker inspect -f '{{range .HostConfig.Binds}}{{println .}}{{end}}' "$WS" 2>/dev/null | grep -c docker.sock)
  local fail=0
  [ "$p" = false ] && ok "Privileged=false" || { bad "Privileged=$p"; fail=1; }
  [ -z "$pid" ] || [ "$pid" = "" ] && ok "PidMode not host (='$pid')" || { bad "PidMode=$pid"; fail=1; }
  [ "$socks" = 0 ] && ok "docker.sock not mounted" || { bad "docker.sock still mounted"; fail=1; }
  return $fail
}
v_rvhealth() {
  # End-to-end proof the webserver can still READ the firewall after the drop:
  # the host-health publisher calls the firewall read; if it still emits
  # firewall_armed, the hostd path (or fallback) works. No PIN needed.
  local env_user env_pass payload
  payload=$(timeout 75 docker exec "$(docker ps -qf name=^mqtt$)" sh -c \
    'mosquitto_sub -h 127.0.0.1 -u "$MQTT_USER" -P "$MQTT_PASS" -t RVC/RV_Health/1 -C 1 -W 70' 2>/dev/null)
  if printf '%s' "$payload" | grep -q '"firewall_armed"'; then
    ok "RVC/RV_Health still publishes firewall_armed (firewall read works)"
    info "   $(printf '%s' "$payload" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("firewall_armed=%s Status=%s"%(d.get("firewall_armed"),d.get("Status")))' 2>/dev/null)"
  else
    bad "no RVC/RV_Health firewall_armed within 70s -- webserver firewall read is broken"
    return 1
  fi
}
v_containers_all_up() {
  local n; n=$(docker ps --format '{{.Status}}' | grep -c healthy)
  info "containers healthy: $n"
}

# --- deploy / edit helpers ---------------------------------------------------

rebuild_ws() {
  info "rebuilding + recreating webserver (brief dashboard blip)..."
  ( cd "$REPO/docker" && docker compose up -d --build "$WS" ) || return 1
  sleep 6
}
recreate_ws() {
  info "recreating webserver from current compose..."
  ( cd "$REPO/docker" && docker compose up -d "$WS" ) || return 1
  sleep 6
}

# Comment the three privilege lines, in the webserver block ONLY, idempotently.
drop_privileges() {
  python3 - "$COMPOSE" <<'PY'
import re, sys
p = sys.argv[1]
lines = open(p).read().splitlines(keepends=True)
svc = [i for i,l in enumerate(lines) if re.match(r'^  [A-Za-z0-9_-]+:\s*$', l)]
w = next(i for i in svc if lines[i].strip() == 'webserver:')
end = next((i for i in svc if i > w), len(lines))
targets = ('pid: host', 'privileged: true', '/var/run/docker.sock:/var/run/docker.sock')
changed = 0
for i in range(w, end):
    s = lines[i]
    if s.lstrip().startswith('#'):
        continue
    stripped = s.strip().lstrip('- ').strip()
    if any(stripped == t or stripped.startswith(t) for t in targets):
        indent = s[:len(s)-len(s.lstrip())]
        lines[i] = f"{indent}# [cutover] {s.lstrip()}"
        changed += 1
open(p, 'w').writelines(lines)
print(f"commented {changed} line(s) in the webserver block")
PY
}

restore_from_git() {
  # Revert ONLY what this script edits -- the compose privilege lines. server.py
  # is the operator's committed code; the script deploys it but never writes it,
  # so touching it here could discard uncommitted dual-path work. Recreating the
  # container from the restored (privileged) compose brings back a working state
  # regardless of which server.py image is loaded.
  ( cd "$REPO" && git checkout -- docker/docker-compose.yml ) 2>/dev/null
}

# --- the steps ---------------------------------------------------------------

step3() {   # dual-path the webserver (deploy committed code + verify)
  say "== Step 3: deploy the dual-path webserver =="
  if ! grep -q "$DUALPATH_MARK" "$SERVER"; then
    bad "server.py has no '$DUALPATH_MARK' marker."
    say "   The step-3 CODE (each privileged call tries sophie-hostd, falls back"
    say "   to nsenter/docker) must be committed first. This script deploys and"
    say "   verifies it; it does not write it. Stopping -- nothing changed."
    return 1
  fi
  rebuild_ws || { bad "rebuild failed"; return 1; }
  v_ws_healthy && v_dash && v_hostd && v_rvhealth || { bad "verify failed -- fix before step 4"; return 1; }
  v_containers_all_up
  say "${c_grn}Step 3 done.${c_off} Privilege is still ON; both paths exist. Exercise the"
  say "dashboard by hand now (reboot + restart especially), then: sudo ./cutover.sh next"
}

step4() {   # drop privileged / pid:host / docker.sock, verify, auto-rollback on failure
  say "== Step 4: drop privileged + pid:host + docker.sock =="
  grep -q "$DUALPATH_MARK" "$SERVER" || { bad "step-3 dual-path code absent; do step 3 first"; return 1; }
  drop_privileges || { bad "compose edit failed"; return 1; }
  recreate_ws || { bad "recreate failed"; restore_from_git; recreate_ws; return 1; }
  say "verifying the de-privileged webserver..."
  if v_priv_dropped && v_ws_healthy && v_dash && v_rvhealth; then
    v_containers_all_up
    say "${c_grn}Step 4 done.${c_off} Webserver is de-privileged and still reads the firewall."
    say "Exercise reboot + container-restart from the dashboard, then: sudo ./cutover.sh next"
  else
    bad "verification FAILED after dropping privilege -- AUTO-ROLLBACK"
    restore_from_git
    recreate_ws
    if v_priv_dropped 2>/dev/null; then :; fi
    v_ws_healthy && v_dash && ok "rolled back to privileged webserver; it is healthy" \
                          || bad "rollback left webserver unhealthy -- see 'Recover by hand' in CUTOVER.md"
    return 1
  fi
}

step5() {   # delete the dead nsenter/docker code (deploy committed cleanup + verify)
  say "== Step 5: deploy the cleaned-up webserver (dead paths removed) =="
  if ! grep -q "$CLEANUP_MARK" "$SERVER"; then
    bad "server.py has no '$CLEANUP_MARK' marker."
    say "   The step-5 CODE (remove the nsenter/docker fallbacks) must be committed"
    say "   first. Stopping -- nothing changed. Step 4's state is unaffected."
    return 1
  fi
  rebuild_ws || { bad "rebuild failed"; return 1; }
  v_priv_dropped && v_ws_healthy && v_dash && v_rvhealth || { bad "verify failed"; return 1; }
  v_containers_all_up
  say "${c_grn}Step 5 done.${c_off} Fallback code is gone. Final step is a reboot test: sudo ./cutover.sh next"
}

step6() {   # reboot test
  say "== Step 6: reboot test =="
  v_hostd || { bad "sophie-hostd not healthy -- do not reboot until it is"; return 1; }
  set_state 6                          # record BEFORE reboot; post-boot verify advances to 7
  say "Rebooting now. After it comes back, log in and run: sudo ./cutover.sh verify"
  say "(that confirms hostd came up before the webserver and reboot/restart work cold)"
  sleep 2
  systemctl reboot
}

verify_current() {
  local s; s=$(get_state)
  case "$s" in
    2) v_hostd && info "daemon installed; next is step 3";;
    3) v_ws_healthy; v_dash; v_hostd; v_rvhealth;;
    4|5) v_priv_dropped; v_ws_healthy; v_dash; v_rvhealth; v_containers_all_up;;
    6) say "== Post-reboot verification =="
       v_hostd && v_priv_dropped && v_ws_healthy && v_dash && v_rvhealth && v_containers_all_up \
         && { set_state 7; say "${c_grn}Step 6 passed -- cutover complete.${c_off}";
              say "Now commit the working-tree changes:";
              say "  cd $REPO && git add docker/docker-compose.yml webserver/server/server.py && git commit"; } \
         || bad "post-reboot verify failed -- see CUTOVER.md 'Recover by hand'";;
    7) ok "cutover already complete";;
  esac
}

status() {
  local s; s=$(get_state)
  say "sophie-hostd cutover -- state: completed through step $s"
  case "$s" in
    2) say "Next: step 3 (deploy dual-path webserver).  Run: sudo ./cutover.sh next";;
    3) say "Next: step 4 (drop privileges).            Run: sudo ./cutover.sh next";;
    4) say "Next: step 5 (delete dead code).           Run: sudo ./cutover.sh next";;
    5) say "Next: step 6 (reboot test).                Run: sudo ./cutover.sh next";;
    6) say "A reboot was issued. After login:          Run: sudo ./cutover.sh verify";;
    7) say "Complete. Commit the working-tree changes (see CUTOVER.md).";;
  esac
  say ""; say "Anytime: sudo ./cutover.sh rollback   (undo to privileged webserver)"
}

rollback() {
  say "Rolling back: restoring compose privileges from git, recreating webserver..."
  say "(server.py is left as-is -- the script never edits it; revert it yourself if needed)"
  restore_from_git
  recreate_ws
  v_ws_healthy && v_dash && ok "webserver restored (privileged) and healthy" \
                        || bad "webserver unhealthy after rollback -- CUTOVER.md 'Recover by hand'"
  set_state 2
  say "State reset to 2 (daemon installed, webserver privileged as before)."
}

# --- dispatch ----------------------------------------------------------------
need_root
cmd="${1:-status}"
case "$cmd" in
  status)  status;;
  verify)  verify_current;;
  rollback) rollback;;
  reset)   set_state "${2:?usage: reset N}"; status;;
  next)
    s=$(get_state)
    case "$s" in
      2) step3 && set_state 3;;
      3) step4 && set_state 4;;
      4) step5 && set_state 5;;
      5) step6;;                 # step6 sets state itself, then reboots
      6) say "A reboot was issued; run 'verify' after login, not 'next'.";;
      7) ok "nothing to do -- cutover complete";;
      *) bad "unknown state '$s'";;
    esac;;
  *) bad "unknown command '$cmd'"; status; exit 1;;
esac
