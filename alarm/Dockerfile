#had to include full buster to get gcc to build Rp.GPIO
# Build: docker build -t alarm .
# RUN  : sudo docker run -it --device /dev/gpiomem alarm
FROM python:3.10.11-buster

WORKDIR /app/alarm

COPY alarm.py .
#COPY mqttclient.py .
COPY requirements.txt .

RUN python -m pip install -r requirements.txt

CMD python3 alarm.py
