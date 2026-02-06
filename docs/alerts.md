# Alerts Examples

This document provides **example** Prometheus alerts for monitoring Oracle health. These are starting points that you should adjust based on your infrastructure and operational requirements.

All examples use [Prometheus Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/) format.

## Basic Alerts

### Account Balance

Alert when the Oracle member account balance is critically low:

```yaml
- alert: OracleAccountBalanceLow
  expr: lido_oracle_account_balance / 10^18 < 1
  for: 10m
  labels:
    severity: critical
  annotations:
    summary: "Dangerously low account balance"
    description: "Account balance is less than 1 ETH. Address: {{ $labels.address }}: {{ $value }} ETH"
```

### Outdated Consensus Layer Data

Alert when the Oracle is processing stale CL data:

```yaml
- alert: OracleOutdatedCLData
  expr: (lido_oracle_genesis_time + ignoring(state) lido_oracle_slot_number{state="head"} * 12) < time() - 300
  for: 1h
  labels:
    severity: critical
  annotations:
    summary: "Outdated Consensus Layer HEAD slot"
    description: "Processed by Oracle HEAD slot {{ $value }} too old"
```

## Cycle Health Alerts

These alerts monitor the Oracle's operational cycles using the `lido_oracle_cycle_count` and `lido_oracle_last_cycle_timestamp` metrics.

> **Note:** The default `MAX_CYCLE_LIFETIME_IN_SECONDS` is 3000 (50 minutes), meaning a single cycle can take up to 50 minutes to complete. Alert thresholds are set accordingly to avoid false positives.

### High Error Rate

Alert when the error rate is too high:

```yaml
- alert: OracleHighErrorRate
  expr: |
    (
      rate(lido_oracle_cycle_count{result="error"}[1h])
      /
      (rate(lido_oracle_cycle_count{result="success"}[1h]) + rate(lido_oracle_cycle_count{result="error"}[1h]) > 0)
    ) > 0.5
  for: 30m
  labels:
    severity: warning
  annotations:
    summary: "High Oracle cycle error rate"
    description: "More than 50% of Oracle cycles are failing. Error rate: {{ $value | humanizePercentage }}"
```

### No Successful Cycles

Alert when there are no successful cycles for a prolonged period:

```yaml
- alert: OracleNoSuccessfulCycles
  expr: time() - lido_oracle_last_cycle_timestamp{result="success"} > 7200
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Oracle has not completed a successful cycle recently"
    description: "No successful Oracle cycle in the last 2 hours. Last successful cycle was {{ $value | humanizeDuration }} ago."
```

### Oracle Completely Stuck

Alert when the Oracle has stopped processing cycles entirely (no cycles at all, not even errors):

```yaml
- alert: OracleStuck
  expr: time() - max(lido_oracle_last_cycle_timestamp) > 7200
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Oracle appears to be stuck"
    description: "No Oracle cycles (successful or failed) have completed in the last 2 hours. The Oracle process may have crashed or hung."
```

> **Note:** Uses `max()` to get the most recent cycle timestamp regardless of result type. The `last_cycle_timestamp{result="error"}` metric only appears after the first error occurs.

## Transaction Alerts

### Failed Transactions

Alert when transactions are failing:

```yaml
- alert: OracleTransactionFailures
  expr: increase(lido_oracle_transactions_count{status="failure"}[24h]) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Oracle transaction failures detected"
    description: "{{ $value }} failed transactions in the last 24 hours."
```

## Full Configuration Example

Example Alertmanager rules file with all alerts combined:

```yaml
groups:
  - name: oracle-basic
    rules:
      - alert: OracleAccountBalanceLow
        expr: lido_oracle_account_balance / 10^18 < 1
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Dangerously low account balance"
          description: "Account balance is less than 1 ETH. Address: {{ $labels.address }}: {{ $value }} ETH"

      - alert: OracleOutdatedCLData
        expr: (lido_oracle_genesis_time + ignoring(state) lido_oracle_slot_number{state="head"} * 12) < time() - 300
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "Outdated Consensus Layer HEAD slot"
          description: "Processed by Oracle HEAD slot {{ $value }} too old"

  - name: oracle-cycle-health
    rules:
      - alert: OracleHighErrorRate
        expr: |
          (
            rate(lido_oracle_cycle_count{result="error"}[1h])
            /
            (rate(lido_oracle_cycle_count{result="success"}[1h]) + rate(lido_oracle_cycle_count{result="error"}[1h]) > 0)
          ) > 0.5
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "High Oracle cycle error rate"
          description: "More than 50% of Oracle cycles are failing."

      - alert: OracleNoSuccessfulCycles
        expr: time() - lido_oracle_last_cycle_timestamp{result="success"} > 7200
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Oracle has not completed a successful cycle recently"
          description: "No successful Oracle cycle in the last 2 hours."

      - alert: OracleStuck
        expr: time() - max(lido_oracle_last_cycle_timestamp) > 7200
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Oracle appears to be stuck"
          description: "No Oracle cycles have completed in the last 2 hours."

  - name: oracle-transactions
    rules:
      - alert: OracleTransactionFailures
        expr: increase(lido_oracle_transactions_count{status="failure"}[24h]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Oracle transaction failures detected"
          description: "Failed transactions detected in the last 24 hours."
```
