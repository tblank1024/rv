---
name: run-ui-debug
description: Start the RV webserver UI in development/debug mode — Python backend (uvicorn, port 8000) plus React dev server with hot reload (port 3000) — following webserver/Makefile's server_start and client_start targets. Use when the user asks to "run the UI in debug mode", "start the dashboard for development", or "launch the webserver locally".
---

# Run Webserver UI in Debug Mode

Launches the `webserver/` app the way the Makefile intends for active development:
the Python backend first, then the React dev server with hot reload. This is
**not** the production build (`make build`) — both processes stay in the
foreground with live logs and auto-reload on save.

Paths below are relative to `/home/tblank/code/tblank1024/rv/webserver/`.

## Pre-flight

1. Confirm `venv/` exists (created by `make setup`). If missing, tell the user
   to run `make setup` first — don't create it yourself, it installs ~600MB of
   dependencies.
2. Confirm `client/node_modules/` exists. If missing, the user needs `make setup`
   (it runs `npm install --legacy-peer-deps`).

## Start the backend (must come up first)

Run in the background so you can keep working and stream its log:

```
cd webserver/server && ../venv/bin/python ./server.py
```

Use `run_in_background` (Bash) and watch the output for:
- `<ip> 8000` — printed constants confirming it bound to port 8000
- `Server startup: Current internet connection is '...'`
- any traceback — surface it to the user immediately rather than continuing

The backend serves on `http://0.0.0.0:8000` (uvicorn, single worker, `log_level=warning`).

## Start the client (only after the backend is up)

```
cd webserver/client && npm start
```

Also run in the background. `react-scripts start` opens the CRA dev server on
`http://localhost:3000` with hot module reload — code edits in `client/src`
apply live without a restart.

## Report back to the user

- Backend: `http://localhost:8000`
- Frontend (open this in a browser): `http://localhost:3000`
- Both processes are running in the background; mention how to stop them
  (Ctrl-C in their terminals, or `TaskStop` if launched as background tasks).

## Notes

- If the user changed `client/src/constants.js`, remind them to run
  `make constants_copy` (or `make build`, which includes it) — the dev server
  does not regenerate `server/constants.json` automatically.
- Don't run `make build` for this — that's the production bundle path and
  shuts down the dev hot-reload workflow.
