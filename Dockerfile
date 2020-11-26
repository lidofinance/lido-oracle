FROM python:3.9-slim-buster

RUN apt-get update \
 && apt-get install -y gcc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --trusted-host pypi.python.org -r requirements.txt

COPY assets ./assets
COPY app ./

ENV ETH1_NODE="" \
    ETH2_NODE="" \
    LIDO_CONTRACT="" \
    MANAGER_PRIV_KEY=""

ENTRYPOINT ["python3", "-u", "oracle.py"]
