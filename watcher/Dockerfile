FROM python:3.10.11-slim-buster
RUN python3 -m pip install --upgrade pip
RUN apt-get update && apt-get install -y gcc

# Install Tkinter
RUN apt-get install tk -y

RUN mkdir -p /app/watacher
RUN mkdir -p /app/watcher/watcherlogs
WORKDIR /app/watcher

COPY watcher.py .
COPY requirements.txt .

RUN python3 -m pip install -r requirements.txt


CMD python3 watcher.py

# To build the container:   docker build -t watcher .
# To run the container:     docker run --name watcher --net=host -v /home/tblank/code/tblank1024/rv/docker/watcherlogs:/app/watcher/watcherlogs watcher