FROM python:3.8-slim

RUN apt-get update \
 && apt-get install -y gcc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --trusted-host pypi.python.org -r requirements.txt

COPY assets ./assets
COPY app ./

ENTRYPOINT ["python3", "-u", "oracle.py"]
