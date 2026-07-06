# Multi-stage build for RV Security monitoring application
FROM node:20-slim AS reactbuild
WORKDIR /app/client
COPY client/package*.json ./
# Install with legacy peer deps for compatibility with d3 packages
RUN npm install --legacy-peer-deps
COPY client/ ./
RUN npm run build

# Constants copy stage - ensures client constants are synced to server
FROM python:3.11-slim AS constants
WORKDIR /app
COPY constantscopy.py ./
COPY client/src/constants.js ./client/src/
RUN mkdir -p server && python3 constantscopy.py client/src/constants.js server/constants.json

FROM python:3.11-slim AS reactbase
# build-essential/git: pip builds + rvglue git dependency
# tzdata: Kasa device timezone responses; usbutils/modemmanager: cellular modem
# iputils-ping/iproute2/curl: connectivity testing and the compose healthcheck
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    tzdata \
    usbutils \
    modemmanager \
    iputils-ping \
    iproute2 \
    curl \
    && rm -rf /var/lib/apt/lists/*
# Create PST8PDT timezone link to handle Kasa device timezone format
RUN ln -sf /usr/share/zoneinfo/America/Los_Angeles /usr/share/zoneinfo/PST8PDT

WORKDIR /app/rvsecurity/server
COPY server/setup.py .
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir --use-pep517 . \
    && python3 -m pip install --no-cache-dir gpiozero lgpio
# kasa_patches.py is written against exactly this version — fail the build,
# not the RV dashboard at 2am, if the pin ever drifts.
RUN python3 -c "from importlib.metadata import version; v = version('python-kasa'); assert v == '0.10.2', f'python-kasa {v} != 0.10.2 — kasa_patches.py must be re-verified'"

FROM reactbase
WORKDIR /app/rvsecurity
# Copy the built React app from the build stage
COPY --from=reactbuild /app/client/build server/build/.
# Copy the synchronized constants from constants stage
COPY --from=constants /app/server/constants.json server/.
# Copy server files
COPY server/server.py server/.
COPY server/server_calcs.py server/.
# Copy Synology NAS controller for Plex server management
COPY server/synology_nas_controller.py server/.
COPY server/synology_nas_config.json.template server/synology_nas_config.json
# Copy Synology authentication credentials (use template; real file should be volume-mounted)
COPY server/synology-password.json.template server/synology-password.json
# Copy Kasa power strip controller (blocking version only)
COPY server/kasa_power_strip.py server/.
# Copy Kasa runtime patches for HS300 new_klap=1 firmware bug in python-kasa 0.10.2
# These are installed into system site-packages AFTER pip install so they survive upgrades.
# The .pth file auto-loads the patch on every Python startup (including subprocess kasa CLI calls).
COPY server/kasa_patches.py server/.
RUN SITE=$(python3 -c "import site; print(site.getsitepackages()[0])") && \
    cp server/kasa_patches.py $SITE/kasa_hs300_patches.py && \
    echo "import kasa_hs300_patches; kasa_hs300_patches.apply()" > $SITE/kasa_hs300_patches.pth
# Copy USB modem manager for cellular modem handling
COPY server/usb_modem_manager.py server/.
# Copy USB hub controller module
COPY usbhub_ascii.py server/.
# Copy WiFi bridge control script for RP Zero 2W configuration
COPY server/RP5toRPZero2WControl.py server/.
#COPY server/mqttclient.py server/.
#COPY server/dgn_variables.json server/.

WORKDIR /app/rvsecurity/server

# Use JSON format for better signal handling
CMD ["python3", "server.py"]
