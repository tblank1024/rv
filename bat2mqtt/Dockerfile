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
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/bat2mqtt
WORKDIR /app/bat2mqtt

COPY bat2mqtt.py .
COPY mqttclient.py .
COPY requirements.txt .
COPY dgn_variables.json .
COPY bluetooth_debug.py .

RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install -r requirements.txt

# Start the Python application directly
CMD ["python3", "-u", "bat2mqtt.py"]

# To build the container:   docker build -t bat2mqtt:latest .
# To run the container:     docker run --name battery --net=host --privileged -v /run/dbus:/run/dbus:ro -v /dev/bus/usb:/dev/bus/usb bat2mqtt:latest