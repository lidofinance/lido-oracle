FROM python:3-slim
WORKDIR /app
COPY assets ./assets
COPY app ./
COPY requirements.txt .
RUN apt-get update && apt-get install -y gcc
RUN pip install --trusted-host pypi.python.org -r requirements.txt
CMD ["python3", "-u", "oracle.py"]
