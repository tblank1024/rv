FROM python:3.10-slim-buster
RUN python3 -m pip install --upgrade pip

RUN apt-get update && apt-get install -y \
    bluetooth \
    bluez \
    libbluetooth-dev \
    libudev-dev \
    python-bluez \
    && rm -rf /var/lib/apt/lists/*

COPY app /app


WORKDIR /app/bat2mqtt

COPY bat2mqtt.py .
COPY mqttclient.py .
COPY requirements.txt .
COPY dgn_variables.json .

RUN python3 -m pip install -r requirements.txt

CMD python3 bat2mqtt.py