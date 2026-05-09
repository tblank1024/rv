help:
# Show available make targets
	@echo "Available targets:"
	@echo "  setup        - Initial setup (install dependencies)"
	@echo "  server_start - Start the Python server"
	@echo "  client_start - Start the React client"
	@echo "  constants_copy - Copy constants from JS to JSON"
	@echo "  build        - Build client for production"
	@echo "  clean        - Remove node_modules and Python cache (frees ~600MB)"
	@echo "  clean-logs   - Clean log files to free additional space"
	@echo "  help         - Show this help message"

setup:
# do this once to setup the environment
	python3 -m venv venv
	./venv/bin/pip install --upgrade pip
	cd server; ../venv/bin/pip install .[dev]
	cd client; npm install --legacy-peer-deps

server_start:
# do this when working on the server.py code
# start_server in a separate cmd window; always first
	cd server; ../venv/bin/python ./server.py

client_start:
# Only need to make client_start if changing the client code
# start_Client in a separate cmd window (note: server must be started first)
	cd client; npm start

constants_copy:
# Copies constants in xx.js file in client to xx.json file in server
# Assumes very simple JS file of just constants
# Example format:
#	export const IPADDR= "192.168.2.177";
#	export const PORT= "8000";
#	...
	python3 constantscopy.py client/src/constants.js server/constants.json


build: constants_copy
#this is only needed when you're ready to deploy locally (non-Docker)
	cd client; npm run-script build
	cd client; rm -Rf ../server/build; mv ./build ../server/

clean:
# Clean up temporary files and dependencies to free disk space
# Removes node_modules (506MB), Python cache files, and compiled Python files
	@echo "Cleaning up temporary files..."
	rm -rf client/node_modules
	rm -rf server/build
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	@echo "Clean complete. Run 'make setup' to reinstall dependencies."

clean-logs:
# Clean up log files to free additional space
	@echo "Cleaning log files..."
	> /home/tblank/code/tblank1024/rv/docker/mqtt/log/mosquitto.log 2>/dev/null || true
	rm -f /home/tblank/code/linuxkidd/rvc-monitor-py/usr/bin/datafile_large.txt 2>/dev/null || true
	rm -f /home/tblank/code/tblank1024/rv/watcher/watcherlogs/*.log 2>/dev/null || true
	@echo "Log cleanup complete."


