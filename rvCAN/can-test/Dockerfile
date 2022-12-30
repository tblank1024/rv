FROM python:3.10-slim-buster
#FROM python:3.10-bullseye

RUN apt update

#RUN ip link set can0 type can bitrate 250000
#RUN ifconfig can0 up


WORKDIR /code 
ADD requirements.txt .
RUN pip install -r requirements.txt 
ADD receive2.py  .


ENTRYPOINT [ "python","/code/receive2.py" ]