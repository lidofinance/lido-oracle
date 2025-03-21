FROM lido-base-oracle:latest as production

WORKDIR /app
COPY . .

ENV PROMETHEUS_PORT 9000
ENV HEALTHCHECK_SERVER_PORT 9010

EXPOSE $PROMETHEUS_PORT
USER www-data

HEALTHCHECK --interval=10s --timeout=3s \
    CMD curl -f http://localhost:$HEALTHCHECK_SERVER_PORT/healthcheck || exit 1

WORKDIR /app/

ENTRYPOINT ["python3", "-m", "src.main"]
