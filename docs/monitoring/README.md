# Monitoring (Prometheus + Alertmanager)

This folder contains example configs to scrape and alert on:

- Performance Web-server (`performance-web:9020/metrics`)
- Performance Collector (`performance-collector:9000/metrics`)
- CSM oracle (`csm-oracle:9000/metrics`)
- CM oracle (`cm-oracle:9000/metrics`)

## Files

- `docs/monitoring/prometheus.yml` - scrape jobs + alerting + rule files wiring
- `docs/monitoring/alerts.yml` - alert rules for the services above (includes epoch/DB health for Performance Collector and perf-oracles)
- `docs/monitoring/alertmanager.yml` - routing/receivers skeleton (plug in Slack/OpsGenie/etc.)

## Notes

- The targets above match `docker-compose.yml` service DNS names on the default compose network; replace them with your real hostnames/IPs in production.
- If you want to template secrets in `alertmanager.yml` via env vars, run Alertmanager with `--config.expand-env` (supported in recent versions).
