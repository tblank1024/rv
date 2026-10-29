# CUTOVER — de-privileging the webserver with sophie-hostd (steps 3–6)

This is the at-the-RV procedure that finishes item #7: pointing the dashboard at
`sophie-hostd` and removing `privileged` / `pid: host` / `docker.sock` from the
webserver. Steps 1–2 (build + install the daemon) are already done; the daemon
is running and inert.

`cutover.sh` drives it. **Your job at Sophie is to run one command, read what it
says, and run the next — the script does the work, verifies, and stops after each
step.** If a step fails it does not advance, and the dangerous step (4) rolls
itself back.

## Before you start

- Have a **root shell that does not depend on the dashboard**: SSH to `10.0.0.1`
  on Sophie's own WiFi, or VNC. Everything here is recoverable from that shell.
- Run everything as root (`sudo`). The driver lives at
  `rv/sophie-hostd/cutover.sh`.
- Confirm the daemon is up: `curl -s 127.0.0.1:12348/api/health`.

## Prerequisite: the server.py code (steps 3 and 5 only)

The script does **not** write Python. Steps 3 and 5 deploy and verify code that
must already be committed:

- **Step 3 needs the dual-path change**: every privileged call in `server.py`
  tries `sophie-hostd` first and falls back to today's `nsenter`/docker path.
  Mark that commit with a comment containing **`sophie-hostd dual-path`** — the
  script refuses step 3 until it sees that marker, so it can never drop privilege
  before the dashboard can actually use the daemon.
Steps 4, 5 and 6 need no code. (Step 5 is an **optional** cosmetic cleanup --
the dual-path from step 3 is the stable end state; the now-dead fallbacks are
harmless and can be removed later as an ordinary commit.)

The endpoint map (which `server.py` call goes to which hostd endpoint) is in
`README.md` and in `rv/plan_history.md` → "Plan: sophie-hostd".

## Running it

```bash
cd /home/tblank/code/tblank1024/rv/sophie-hostd

sudo ./cutover.sh            # where am I, what's next
sudo ./cutover.sh next       # do the next step, verify, stop
sudo ./cutover.sh verify     # re-run the current step's checks
sudo ./cutover.sh rollback   # undo to the privileged webserver, any time
```

Progress is saved in `/var/lib/sophie-cutover.state`, which survives the step-6
reboot.

### What each `next` does

| State | `next` runs | Then |
|---|---|---|
| 3 | **Step 3** — rebuild+deploy the dual-path webserver; verify dashboard, hostd, and that `RVC/RV_Health` still carries `firewall_armed`. Privilege still ON. | Exercise reboot + restart from the dashboard by hand, then `next`. |
| 4 | **Step 4** — comment `pid: host`, `privileged: true`, `docker.sock` in the **webserver block only**; recreate; verify privilege is gone **and** the firewall read still works. **Auto-rolls-back on any failure.** | Exercise reboot + restart again, then `next`. |
| 5 | **Step 5** — OPTIONAL dead-code note; deploys nothing (the fallbacks are harmless after de-privilege). | `next`. |
| 6 | **Step 6** — reboot. | After login: `sudo ./cutover.sh verify`. |

After step 6's reboot, `verify` confirms the daemon came up before the webserver
needed it and that everything reads cold; on success it tells you to commit the
working-tree changes:

```bash
cd /home/tblank/code/tblank1024/rv
git add docker/docker-compose.yml webserver/server/server.py && git commit
```

Until you commit, nothing is permanent — `git checkout` undoes it.

### Why step 4 is safe to run with you watching remotely

After dropping privilege it checks, with no PIN needed, that `RVC/RV_Health` is
still published with `firewall_armed` — which is only possible if the webserver
can still read the firewall, i.e. the hostd path works. If that (or the
dashboard health, or the privilege-actually-dropped check) fails, the script
restores the compose from git and recreates the webserver **privileged** before
returning. So a broken dual-path cannot leave you stranded.

## Also do before step 4: the modem / `/sys/bus/usb` piece

Independent of the script, and needed before privilege comes off (it also needs
`pid: host`): move the modem's `/sys/bus/usb` bind/unbind — **and the host MTP
process kill in `prepare_cellular_modem()`** — to `usbhub-api` (or hostd), then
drop the `/sys/bus/usb:rw` mount (line ~388, webserver block). Until that's done,
the cellular "prepare modem" path breaks once `pid: host`/`privileged` are gone.
The script does not touch this; it is tracked in `rv/plan_history.md`.

## Recover by hand

The driver's `rollback` covers the normal cases. If you ever need to act without
it, these work from any root shell and need neither the dashboard nor hostd:

```bash
docker restart <name>                                    # restart one container
docker compose -f /home/tblank/code/tblank1024/rv/docker/docker-compose.yml restart
sudo systemctl reboot                                    # reboot the Pi
sudo systemctl restart sophie-hostd                      # bounce the broker

# full undo of the cutover's own edits:
cd /home/tblank/code/tblank1024/rv
git checkout -- docker/docker-compose.yml
cd docker && docker compose up -d webserver              # back to privileged
```

The only window where the webserver depends on the daemon for reboot/restart is
after step 4. If hostd is down then, drive reboot/restart from the shell above
and either `systemctl restart sophie-hostd` or roll back — you are never stuck.
This is why step 6 (the reboot) is last and done at the RV.
