FROM python:3.11-slim-bookworm

# Install system dependencies for Bluetooth and DBus
RUN apt-get update && apt-get install -y \
    dbus \
    libdbus-1-dev \
    bluez \
    bluez-tools \
    dbus-x11 \
    bluetooth \
    libbluetooth-dev \
    pkg-config \
    rfkill \
    libglib2.0-dev \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/bat2mqtt
WORKDIR /app/bat2mqtt

# Copy only the files needed for bat2mqtt implementation
COPY bat2mqtt.py .
COPY mqttclient.py .
COPY dgn_variables.json .
COPY requirements.txt .

# Install Python dependencies
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install -r requirements.txt

# Start the regular implementation directly
CMD ["python3", "-u", "bat2mqtt.py"]

# To build: docker build -f Dockerfile.pygatt -t bat2mqtt:pygatt .
