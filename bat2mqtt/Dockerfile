FROM python:3.10.11-slim-buster
RUN apt-get update && apt-get install -y \
     dbus \
     libdbus-1-dev \
     bluez \
     bluez-tools


RUN mkdir -p /app/bat2mqtt
WORKDIR /app/bat2mqtt

COPY bat2mqtt.py .
COPY mqttclient.py .
COPY requirements.txt .
COPY dgn_variables.json .

RUN python3 -m pip install -r requirements.txt
RUN apt-get install -y dbus-x11


CMD python3 bat2mqtt.py

# To build the container:   docker build -t battery .
# To run the container:     docker run --name battery --net=host --privileged -v /dev/bus/usb:/dev/bus/usb battery