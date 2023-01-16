FROM python:3.10-slim-buster

WORKDIR /app/mqttlistener

COPY mqttclient.py .
COPY subscriptions.yml .
COPY requirements.txt .

#ruamel installed independently since there is no C complier
RUN python -m pip install --no-deps ruamel.yaml

RUN python -m pip install -r requirements.txt

CMD python3 mqttclient.py

