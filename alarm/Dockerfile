
FROM python:3.10-slim-buster

WORKDIR /app/rvalarm

COPY alarm.py .
COPY requirements.txt .

RUN python -m pip install -r requirements.txt

CMD python3 alarm.py
