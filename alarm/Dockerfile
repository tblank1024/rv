# Updated for Raspberry Pi 5 with libgpiod support
# Build: docker build -t alarm .
# RUN  : sudo docker run -it --device /dev/gpiomem --device /dev/gpiochip0 alarm
FROM python:3.10-slim
RUN python3 -m pip install --upgrade pip
RUN apt-get update && apt-get install -y \
    gcc \
    libgpiod-dev \
    python3-libgpiod \
    gpiod

WORKDIR /app/alarm

COPY alarm.py .
#COPY mqttclient.py .
COPY requirements.txt .

RUN python -m pip install -r requirements.txt

CMD ["python3", "alarm.py"]
