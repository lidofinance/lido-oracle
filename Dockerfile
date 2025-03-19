FROM python:3.12.4-slim as base


RUN apt-get update && apt-get install -y --no-install-recommends -qq \
    libffi-dev=3.4.4-1 \
    g++=4:12.2.0-3 \
    curl=7.88.1-10+deb12u12 \
 && find /var/log -type f -name '*.log' -print -exec truncate -s0 '{}' \; \
 && find /var/cache/ldconfig -type f -delete \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

FROM base as builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    VENV_PATH="/.venv"

# ugly hack for C extension from lru-dict
ENV CFLAGS="-g0 -O2 -ffile-prefix-map=/src=."

ENV PATH="$VENV_PATH/bin:$PATH"

ENV POETRY_VERSION=1.3.2

RUN pip install --no-compile --no-cache-dir poetry==$POETRY_VERSION

WORKDIR /
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-cache

RUN rm -rf /root/.cache $VENV_PATH/src \
  && find $VENV_PATH -type f -name 'RECORD' -delete \
  && find $VENV_PATH -type f -name '*.pyc' -delete \
  && find /root/.local -type f -name '*.pyc' -delete \
  && find /usr/local -type f -name '*.pyc' -delete

FROM base as production

ENV VENV_PATH="/.venv"

COPY --from=builder $VENV_PATH $VENV_PATH
WORKDIR /app
COPY . .

RUN apt-get clean && find /var/lib/apt/lists/ -type f -delete && chown -R www-data /app/

ENV PROMETHEUS_PORT=9000
ENV HEALTHCHECK_SERVER_PORT=9010

EXPOSE $PROMETHEUS_PORT
USER www-data

HEALTHCHECK --interval=10s --timeout=3s \
    CMD curl -f http://localhost:$HEALTHCHECK_SERVER_PORT/healthcheck || exit 1

WORKDIR /app/

ENTRYPOINT ["python3", "-m", "src.main"]
