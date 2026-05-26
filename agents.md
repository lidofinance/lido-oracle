# lido-oracle

Oracle daemon for the Lido decentralized staking protocol. Monitors state across Execution and Consensus layers, submits periodic reports to Lido smart contracts.

## Architecture

Four oracle modules, each with its own reporting frame:

| Module       | Command                                    | Frame             | Purpose                                                 |
|--------------|--------------------------------------------|-------------------|---------------------------------------------------------|
| `accounting` | `make run-module ORACLE_MODULE=accounting` | ~24h / 225 epochs | TVL updates, validator status, withdrawals, bunker mode |
| `ejector`    | `make run-module ORACLE_MODULE=ejector`    | ~5h / 45 epochs   | Validator exit requests to fund withdrawals             |
| `csm`        | `make run-module ORACLE_MODULE=csm`        | 6300 epoches      | Community Staking Module oracle                         |
| `cm`         | `make run-module ORACLE_MODULE=cm`         | 6300 epoches      | Curated Module V2 oracle                                |

Sidecars: `performance_collector`, `performance_web_server`

Each module flow: **Waiting → Data collection → Hash consensus → Report submission**

## Source layout

```
src/
├── main.py                  # Entry point — dispatches to module entrypoints
├── variables.py             # All env vars parsed here (single source of truth)
├── constants.py
├── types.py                 # OracleModuleName enum and shared types
├── runtime.py               # Startup logging, Prometheus HTTP server, healthcheck pulse
├── modules/
│   ├── common/              # Shared daemon base (daemon_module.py, types.py)
│   ├── oracles/
│   │   ├── common/          # ConsensusModule, OracleModule, exceptions, runtime
│   │   ├── accounting/      # Accounting oracle
│   │   │   └── third_phase/ # Extra-data encoding (extra_data.py, types.py)
│   │   ├── ejector/         # Exit Bus oracle
│   │   └── staking_modules/ # CSM + CM oracles
│   │       ├── common/      # Shared state, distribution, tree, log helpers
│   │       ├── community_staking/  # CSM oracle (csm.py, entrypoint.py)
│   │       └── curated/     # Curated Module V2 oracle (cm.py, entrypoint.py)
│   ├── checks/              # Environment/connectivity checks (suites/)
│   └── sidecars/
│       └── performance/
│           ├── collector/   # Epoch data collection daemon
│           ├── common/      # DB layer (db.py, types.py)
│           └── web/         # FastAPI metrics server
├── providers/
│   ├── consensus/           # Beacon node client
│   ├── execution/           # EL client + contracts
│   │   └── contracts/       # One file per contract ABI wrapper
│   ├── keys/                # Keys API client
│   ├── ipfs/                # IPFS upload (Pinata, Kubo, Filebase, Lido)
│   └── performance/         # Performance data provider
├── services/                # Business logic (stateless, testable)
│   ├── validator_state.py
│   ├── exit_order_iterator.py
│   ├── bunker.py / bunker_cases/
│   ├── safe_border.py
│   ├── withdrawal.py
│   ├── prediction.py
│   ├── staking_vaults.py
│   └── deposit_signature_verification.py
├── metrics/
│   ├── logging.py           # Structured JSON logger used across all modules
│   ├── healthcheck_server.py
│   └── prometheus/          # Per-module metric definitions
├── utils/                   # Stateless helpers — import freely, no side effects
│   ├── web3converter.py     # Slot/epoch/blockstamp conversions
│   ├── blockstamp.py
│   ├── validator_balance.py
│   ├── cache.py
│   ├── events.py
│   ├── transaction.py
│   └── car/                 # CAR file encoding for IPFS
└── web3py/
    └── extensions/          # web3.py middleware: lido_validators, staking_module,
                             # delegation, ipfs, telemetry_data_bus, tx_utils, …
```

## Key commands

All dev commands run inside Docker container. Start the container first with `make up`.

```bash
make up                          # Build dev image, start container (idempotent)
make sh                          # Interactive shell inside container
make lint                        # ruff format + ruff check + pyright
make test                        # Run all tests
make test ORACLE_TEST_PATH=tests/modules/accounting/  # Run specific tests
make run-module ORACLE_MODULE=accounting  # Run a module locally
make sidecars-up                 # Start Postgres + performance sidecars
```

Local (without Docker):
```bash
poetry install
poetry run pytest tests/
poetry run ruff format tests && ruff check src tests && pyright src
```

## Testing

**Target: ~90% unit / ~10% integration. 95–100% coverage for core modules.**

Every test must have exactly one marker — `@pytest.mark.unit` or `@pytest.mark.integration`. Never both.

Additional integration markers: `@pytest.mark.mainnet`, `@pytest.mark.testnet`, `@pytest.mark.fork`

### Test naming convention

```
test_<method_name>__<scenario>__<expected_behavior>
```

Examples:
- `test_fetch__valid_cid__returns_content`
- `test_fetch__request_fails__raises_fetch_error`

### Structure: AAA pattern inside test classes

```python
@pytest.mark.unit
class TestMyModule:

    @pytest.fixture
    def subject(self):
        return MyModule(...)

    def test_method__scenario__expected(self, subject):
        # Arrange
        ...
        # Act
        result = subject.method(...)
        # Assert
        assert result == expected
```

### Web3 fixtures

- `web3` — mocked with `eth_tester` MockBackend (for unit tests, no real network)
- `web3_integration` — real Web3 connected to live nodes (requires env vars)

Unit tests have network access **blocked automatically**. Use `responses` library for HTTP mocks.

### Mutation testing

```bash
poetry run mutmut run \
    --paths-to-mutate=src/services/staking_vaults.py \
    --runner="pytest -x -m unit -q tests/modules/accounting/staking_vault"
poetry run mutmut results
```

Target mutation score: **75%+**

## Code quality

- **Formatter/linter**: `ruff` (line length 120, Python 3.14, isort integrated)
- **Type checker**: `pyright` (basic mode, stubs in `stubs/`)
- **Pre-commit**: `make install-pre-commit` — runs lint + test on commit

`ruff` configuration: `quote-style = "preserve"` — don't change quote style when editing.

## Environment variables

All parsed in `src/variables.py`. Key vars:

| Variable                 | Required for                                 |
|--------------------------|----------------------------------------------|
| `EXECUTION_CLIENT_URI`   | All oracle modules                           |
| `CONSENSUS_CLIENT_URI`   | All oracle modules                           |
| `KEYS_API_URI`           | All oracle modules                           |
| `LIDO_LOCATOR_ADDRESS`   | Accounting, Ejector, Check                   |
| `STAKING_MODULE_ADDRESS` | CSM, CM                                      |
| `MEMBER_PRIV_KEY`        | Submitting reports (live mode)               |
| `DAEMON`                 | `True` by default — set `False` for one-shot |

Copy `.env.example` → `.env` before running locally.

## Stack

- **Python 3.14** (pinned, not 3.13 or 3.15)
- **Poetry** for dependency management (`poetry.toml` enforces local venv in `.venv/`)
- **web3.py 7.x** + `web3-multi-provider` for multi-endpoint resilience
- **FastAPI + uvicorn** for performance web server sidecar
- **SQLModel + psycopg2** for performance data persistence (Postgres)
- **Prometheus** metrics exposed by all modules

## AI instruction files

Five scoped instruction files live in `.github/instructions/` and apply automatically to matching file globs. When working in those paths, follow them — they take precedence over general style preferences:

| File                             | Applies to                                                                       | Focus                                                                  |
|----------------------------------|----------------------------------------------------------------------------------|------------------------------------------------------------------------|
| `oracle-logic.instructions.md`   | `src/modules/oracles/**`, `src/services/**`, `src/providers/**`, `src/web3py/**` | Cycle timing, report ordering, finalized-data assumptions, bunker mode |
| `python-quality.instructions.md` | `src/**/*.py`                                                                    | Ruff/pyright compliance, type annotations, code structure              |
| `security.instructions.md`       | `src/**/*.py`                                                                    | Secret handling, no logging of keys, safe external calls               |
| `testing.instructions.md`        | `tests/**/*.py`                                                                  | Markers, AAA pattern, mock strategy, coverage expectations             |
| `documentation.instructions.md`  | `docs/**`, `*.md`                                                                | Operator-facing accuracy, env var docs, changelog entries              |

## Important constraints

- **Do not change Python version** — `json-stream-rs-tokenizer` and other deps are pinned to `>=3.14,<3.15`
- **Do not skip pre-commit hooks** — they enforce ruff + pyright on all staged files
- **All on-chain write paths** must go through the consensus flow (HashConsensus → report submission); never submit directly
- **`src/web3py/contract_tweak.py`** is excluded from pyright (extensive upstream copy-paste) — don't add new logic there
- **`src/utils/car/schemes/unixfs_pb2.py`** is generated protobuf — do not edit manually
- Gas estimation adds `TX_GAS_ADDITION` (default 100k) to handle edge cases in same-block submissions

## Docs

- `docs/development.md` — local setup guide (Docker and host-based workflows)
- `docs/testing.md` — testing strategy and patterns (authoritative)
- `docs/alerts.md` — example Prometheus alert rules for oracle health monitoring
- `docs/delegation.md` — delegation feature: separating protocol permissions from oracle hot keys via DelegationContract
- `docs/reproducible-builds.md` — how to produce and verify reproducible Docker images
- `docs/monitoring/` — Prometheus and Alertmanager config examples
- `README.md` — operator manual and module overview

### External — docs.lido.fi

**Operator guides**
- [Oracle Operator Manual](https://docs.lido.fi/guides/oracle-operator-manual/)
- [Tooling Overview](https://docs.lido.fi/guides/tooling/)

**Oracle specifications**
- [Accounting Oracle spec](https://docs.lido.fi/guides/oracle-spec/accounting-oracle/)
- [Validators Exit Bus spec](https://docs.lido.fi/guides/oracle-spec/validator-exit-bus/)
- [Validator Exits and Penalties](https://docs.lido.fi/guides/oracle-spec/penalties/)

**Smart contracts**
- [HashConsensus](https://docs.lido.fi/contracts/hash-consensus/)
- [AccountingOracle](https://docs.lido.fi/contracts/accounting-oracle/)
- [OracleReportSanityChecker](https://docs.lido.fi/contracts/oracle-report-sanity-checker/)
- [OracleDaemonConfig](https://docs.lido.fi/contracts/oracle-daemon-config/)

**CSM**
- [CSM intro](https://docs.lido.fi/staking-modules/csm/intro/)
- [CSM rewards](https://docs.lido.fi/staking-modules/csm/rewards/)
- [CSM penalties](https://docs.lido.fi/staking-modules/csm/penalties/)
- [CSM validator exits](https://docs.lido.fi/staking-modules/csm/validator-exits/)
