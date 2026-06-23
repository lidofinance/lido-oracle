# Lido Oracle GitHub Copilot Instructions

## Overview
Lido Oracle is critical DeFi infrastructure processing tens of billions in staked ETH. Apply security-first mindset to ALL code changes - any vulnerability could impact billions in user funds.

## Oracle Context
- `accounting`: main protocol accounting oracle. Builds frame-based protocol reports, updates TVL-related state, processes withdrawal/finalization inputs, controls bunker-related values, and submits extra data
- `ejector`: validator exit oracle. Determines which validators should exit to satisfy withdrawal demand and reports exit data on-chain
- `csm`: Community Staking Module oracle. Consumes performance data, publishes report artifacts to IPFS, and reports performance/fee data for the community staking module
- `cm`: Curated Module oracle. Similar staking-module reporting flow for curated staking modules
- `check`: preflight and health-check module that validates environment and external dependencies before running an oracle
- `performance_collector`: sidecar that ingests consensus-layer attestation/performance data and stores it in Postgres
- `performance_web_server`: sidecar API serving performance data to staking-module oracles

## Architecture Notes
- Oracle code reads state from Execution Layer, Consensus Layer, and Keys API (KAPI), then builds deterministic frame-based reports for contracts. CSM module additionally reads data from performance collector sidecars
- `accounting` and `ejector` are the most safety-critical on-chain reporting paths; bugs here are higher severity than ordinary refactors
- `csm` and `cm` depend on the performance sidecars plus IPFS publishing; review data freshness, consistency, and failure handling carefully
- Be alert for bugs caused by mixing finalized reference state with latest-chain state or by moving side effects into the wrong reporting phase

## Review Principles
- Comment only with high confidence that a real issue exists or a materially safer implementation is available
- Prioritize correctness, safety, protocol invariants, and missing validation over style nitpicks
- Explain why flagged issues are problematic, including protocol or security impact when relevant
- Be concise and actionable: prefer one issue per comment and suggest the smallest safe fix

## Priority Review Areas

- `SECURITY FIRST`: prioritize vulnerabilities, unsafe secret handling, and security regressions
- `ORACLE LOGIC`: preserve cycle timing, report ordering, finalized-data assumptions, and consensus/reportability checks
- `TESTING`: prefer comments about missing tests only for changed behavior, invariants, or integration boundaries
- `DOCUMENTATION`: ensure env var, API, workflow, and operator-facing behavior changes update docs

## CI Context
- Avoid flagging issues already enforced by CI unless the change clearly bypasses or weakens that protection
- CI already runs `pytest -m 'not fork' tests`, `ruff format --check tests`, `ruff check` for changed Python files, `pyright src`, Docker image build, and Docker reproducibility checks
- Prefer review comments about missing tests only when behavior, safety checks, protocol invariants, or integration boundaries changed

## Key Patterns
- Secrets belong only in private env handling and must never be logged
- Changes around `ref_slot`, finalized slots, report phases, bunker mode, or transaction sending deserve extra scrutiny
