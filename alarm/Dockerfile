FROM python:3.10-slim-buster

WORKDIR /app/rvalarm

COPY alarm.py .
COPY requirements.txt .

#ruamel installed independently since there is no C complier

RUN python -m pip install -r requirements.txt

CMD python3 alarm.py
