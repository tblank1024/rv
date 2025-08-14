# Container for Raspberry Pi 4B
# builds VE.Direct to MQTT bridge for Solar Controller
#
# Build: docker build -t solar .
# RUN  : docker run --name solar --net=host --device=/dev/ttyAMA0 solar
FROM python:3.10-slim
RUN python3 -m pip install --upgrade pip
RUN apt-get update && apt-get install -y \
    git

WORKDIR /app/solar

COPY ve-direct.py .
COPY requirements.txt .

RUN python -m pip install -r requirements.txt
CMD python3 ve-direct.py
