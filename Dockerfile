FROM python:3.8-slim as builder

RUN apt-get update && apt-get install -y gcc

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-use-pep517 --trusted-host pypi.python.org -r requirements.txt

FROM python:3.8-slim as production

WORKDIR /app

RUN mkdir /var/www && chown www-data /var/www && \
    apt-get update && apt-get install -y curl && \
    apt-get clean && find /var/lib/apt/lists/ -type f -delete && \
    chown www-data /app/

ENV PATH=$PATH:/usr/local/bin
ENV PYTHONPATH="/usr/local/lib/python3.8/site-packages/"

# Set metadata
ARG VERSION
ARG COMMIT_DATETIME
ARG BUILD_DATETIME
ARG TAGS
ARG BRANCH
ARG COMMIT_MESSAGE
ARG COMMIT_HASH
LABEL VERSION="$VERSION"
LABEL COMMIT_DATETIME="$COMMIT_DATETIME"
LABEL BUILD_DATETIME="$BUILD_DATETIME"
LABEL TAGS="$TAGS"
LABEL BRANCH="$BRANCH"
LABEL COMMIT_MESSAGE="$COMMIT_MESSAGE"
LABEL COMMIT_HASH="$COMMIT_HASH"
ENV VERSION=${VERSION}
ENV COMMIT_DATETIME=${COMMIT_DATETIME}
ENV BUILD_DATETIME=${BUILD_DATETIME}
ENV TAGS=${TAGS}
ENV BRANCH=${BRANCH}
ENV COMMIT_MESSAGE=${COMMIT_MESSAGE}
ENV COMMIT_HASH=${COMMIT_HASH}

EXPOSE 8000
USER www-data

COPY --from=builder /usr/local/ /usr/local/
COPY assets ./assets
COPY app ./

HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8000/healthcheck || exit 1

ENTRYPOINT ["python3", "-u", "oracle.py"]
