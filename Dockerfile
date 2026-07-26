# syntax=docker/dockerfile:1.9.0
FROM python:3.14-slim AS base

ARG POETRY_VERSION=2.3.2
ARG SOURCE_DATE_EPOCH

RUN apt-get update && apt-get install -y --no-install-recommends -qq \
    libffi-dev=3.4.8-2 \
    g++=4:14.2.0-1 \
    curl=8.14.1-2+deb13u4 \
    swig=4.3.0-1 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && rm -rf /var/cache/* \
 && rm -rf /var/log/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VIRTUALENVS_IN_PROJECT=false \
    POETRY_NO_INTERACTION=1 \
    POETRY_INSTALLER_PARALLEL=false \
    # No credential store exists in a build container, but poetry still probes one before
    # installing: that pulls in keyring -> SecretStorage -> cryptography's native module,
    # which is a pointless dependency here and an observed crash source on arm64 hosts.
    PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring" \
    VENV_PATH="/opt/venv" \
    # Building reproducible .so files by enforcing consistent CFLAGS across builds
    CFLAGS="-g0 -O2 -ffile-prefix-map=/src=."

ENV PATH="$VENV_PATH/bin:$PATH"

FROM base AS builder

ARG POETRY_VERSION
RUN pip install --no-cache-dir poetry==${POETRY_VERSION}

# Only needed so build_blst.sh can fetch blst when the build context was produced by a
# checkout without submodules. Stays in this stage; production copies just the venv.
RUN apt-get update && apt-get install -y --no-install-recommends -qq \
    git=1:2.47.3-0+deb13u1 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /
COPY pyproject.toml poetry.lock ./
COPY scripts/build_blst.sh scripts/build_blst.sh
COPY vendor/blst vendor/blst

RUN python3 -m venv "$VENV_PATH" && \
    VIRTUAL_ENV="$VENV_PATH" poetry install --only main --no-root --no-cache && \
    sh scripts/build_blst.sh && \
    find "$VENV_PATH" -type d -name '.git' -exec rm -rf {} + && \
    find "$VENV_PATH" -name '*.dist-info' -exec rm -rf {}/RECORD \; && \
    find "$VENV_PATH" -name '*.dist-info' -exec rm -rf {}/WHEEL \; && \
    find "$VENV_PATH" -path '*/oz_merkle_tree*/LICENSE*' -type f -delete && \
    find "$VENV_PATH" -path '*/oz_merkle_tree*' -type d -name 'licenses' -exec rm -rf {} + && \
    find "$VENV_PATH" -name '__pycache__' -exec rm -rf {} +

FROM base AS development

ARG POETRY_VERSION
RUN pip install --no-cache-dir poetry==${POETRY_VERSION}

RUN apt-get update && apt-get install -y --no-install-recommends -qq \
    git=1:2.47.3-0+deb13u1 \
    htop=3.4.1-5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN bash -c "set -o pipefail && curl -L https://foundry.paradigm.xyz | bash && /root/.foundry/bin/foundryup"
ENV PATH="/root/.foundry/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN python3 -m venv "$VENV_PATH" && \
    VIRTUAL_ENV="$VENV_PATH" poetry install --no-root --with dev

FROM base AS production

COPY --from=builder $VENV_PATH $VENV_PATH

# blst is not a PyPI dependency: it is compiled in the builder stage. Were it ever missing
# from the venv, the image would start fine and only fail on the first deposit signature
# check — mid-report, in production. Assert it here so such an image cannot be published,
# whichever pipeline builds it.
RUN python3 -c "import blst" || { \
      echo "FATAL: blst is missing from the image."; \
      echo "The build context had no vendor/blst — check out submodules before building:"; \
      echo "  actions/checkout with 'submodules: recursive', or 'git submodule update --init --recursive'"; \
      exit 1; \
    }

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

ENTRYPOINT ["/opt/venv/bin/python3", "-m", "src.main"]
