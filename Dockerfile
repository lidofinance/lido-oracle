FROM python:3.9-slim as base

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=true

RUN apt-get update && apt-get install -y --no-install-recommends -qq gcc=4:10.2.1-1 g++=4:10.2.1-1 curl=7.74.0-1.3+deb11u1 \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base as builder

ENV POETRY_VERSION=1.1.13
RUN pip install --no-cache-dir poetry==$POETRY_VERSION

COPY pyproject.toml poetry.lock ./
RUN python -m venv --copies /venv

RUN . /venv/bin/activate && poetry install --no-dev --no-root

FROM base as production

COPY --from=builder /venv /venv

RUN mkdir -p /var/www && chown www-data /var/www && \
    chown -R www-data /app/ && chown -R www-data /venv

ENV PYTHONPATH="/venv/lib/python3.9/site-packages/"
ENV PATH=$PATH:/venv/bin
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PULSE_SERVER_PORT 8000
ENV PROMETHEUS_PORT 8000

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

EXPOSE $PROMETHEUS_PORT
USER www-data

COPY --from=builder /usr/local/ /usr/local/
COPY assets ./assets
COPY app ./

HEALTHCHECK --interval=10s --timeout=3s \
    CMD curl -f http://localhost:$PULSE_SERVER_PORT/healthcheck || exit 1

ENTRYPOINT ["python3", "-u", "oracle.py"]
