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
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/bat2mqtt
WORKDIR /app/bat2mqtt

COPY bat2mqtt.py .
COPY mqttclient.py .
COPY requirements.txt .
COPY dgn_variables.json .

RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install -r requirements.txt

CMD python3 bat2mqtt.py

# To build the container:   docker build -t battery .
# To run the container:     docker run --name battery --net=host --privileged -v /run/dbus:/run/dbus:ro battery