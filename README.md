# <img src="https://docs.lido.fi/img/logo.svg" alt="Lido" width="46"/> Lido Oracle

[![Tests](https://github.com/lidofinance/lido-oracle/workflows/Tests/badge.svg?branch=daemon_v2)](https://github.com/lidofinance/lido-oracle/actions)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Oracle daemon for Lido decentralized staking service. Collects and reports CL states to the Lido dApp contracts running on Ethereum EL side.

There are two types of oracles:
  - **accounting:**
      reports info about validators count, balances (validators, withdrawal vault, EL rewards vault), count of exited validators
  - **ejector:**
      reports info about next validators to be ejected (to initiate exit from CL)

# Usage

## Setup
Oracle daemon must be run using a docker container. Images is available on [Docker Hub](https://hub.docker.com/r/lidofinance/oracle).
Pull the image using the following command:
```bash
docker pull lidofinance/oracle:{tag}
```
Where `{tag}` is a version of the image. You can find the latest version in the [releases](https://github.com/lidofinance/lido-oracle/releases)
**OR**\
You can build it locally using the following command:
```bash
docker build -t lidofinance/oracle .
```

## Run
1. Use `.env.example` file content to create your own `.env` file.  
      There are two options to run Oracle:
   - `dry mode` (by default)
   - `production mode` 
\
\
      To run Oracle in `production mode` set `MEMBER_PRIV_KEY` environment variable in `.env` file:
      ```bash
      MEMBER_PRIV_KEY={value}
      ```
      Where `{value}` is a private key of the Oracle member account.
2. Run the container using the following command:
      ```bash
      docker run --env-file .env lidofinance/oracle:{tag} {type}
      ```
      Where
   - `{tag}` is a version of the image. You can find the latest version in the [releases](https://github.com/lidofinance/lido-oracle/releases)
   - `{type}` is a type of the Oracle. There are two types of oracles:
      - `accounting`
      - `ejector`

## Env variables

| Name                                         | Description                                                                                                                                                              | Required | Example value           |
|----------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|-------------------------|
| `EXECUTION_CLIENT_URI`                       | URI of the Execution Layer client                                                                                                                                        | True     | `http://localhost:8545` |
| `CONSENSUS_CLIENT_URI`                       | URI of the Consensus Layer client                                                                                                                                        | True     | `http://localhost:5052` |
| `KEYS_API_URI`                               | URI of the Keys API                                                                                                                                                      | True     | `http://localhost:8080` |
| `LIDO_LOCATOR_ADDRESS`                       | Address of the Lido contract                                                                                                                                             | True     | `0x1...`                |
| `MEMBER_PRIV_KEY`                            | Private key of the Oracle member account                                                                                                                                 | False    | `0x1...`                |
| `FINALIZATION_BATCH_MAX_REQUEST_COUNT`       | The size of the batch to be finalized per request (The larger the batch size, the more memory of the contract is used but the fewer requests are needed)                 | False    | `1000`                  |
| `ALLOW_REPORTING_WHILE_BUNKER`               | Allow the Oracle to do report if bunker mode is active                                                                                                                   | False    | `True`                  |
| `TX_GAS_MULTIPLIER`                          | Used to modify gas parameter that used in transaction. (gas = estimated_gas * TX_GAS_MULTIPLIER)                                                                         | False    | `1.75`                  |
| `CYCLE_SLEEP_IN_SECONDS`                     | The time between cycles of the oracle's activity                                                                                                                         | False    | `12`                    |
| `SUBMIT_DATA_DELAY_IN_SLOTS`                 | The difference in slots between submit data transactions from Oracles. It is used to prevent simultaneous sending of transactions and, as a result, transactions revert. | False    | `6`                     |
| `HTTP_REQUEST_RETRY_COUNT`                   | Total number of retries to fetch data from endpoint                                                                                                                      | False    | `5`                     |
| `HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS` | The delay http provider sleeps if API is stuck                                                                                                                           | False    | `12`                    |
| `HTTP_REQUEST_TIMEOUT`                       | Timeout for HTTP requests                                                                                                                                                | False    | `300`                   |

## Monitoring
TBD

### Dashboard
TBD

### Alerts
TBD

### Metrics
TBD

# Development

Python version: 3.11

## Setup

1. [Setup poetry](https://python-poetry.org/docs/#installation)
2. Install dependencies
```bash
poetry install
```

## Startup

Required variables
```bash
export EXECUTION_CLIENT_URI=...
export CONSENSUS_CLIENT_URI=...
export KEYS_API_URI=...
export LIDO_LOCATOR_ADDRESS=...
```
Run oracle module
```bash
poetry run python -m src.main {module}
```

Where `{module}` is one of:
- `accounting`
- `ejector`

## Tests

[Testing guide](./tests/README.md)

```bash
poetry run pytest .
```

## Code quality
Used both pylint and mypy for code quality checks.
See the [configuration](pyproject.toml) for details for each linter.

```bash
pylint src
```
```bash
mypy src
```

# License

2023 Lido <info@lido.fi>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License, or any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the [GNU General Public License](LICENSE)
along with this program. If not, see <https://www.gnu.org/licenses/>.

## Release flow

To create new release:

1. Merge all changes to the `master` branch
1. Navigate to Repo => Actions
1. Run action "Prepare release" action against `master` branch
1. When action execution is finished, navigate to Repo => Pull requests
1. Find pull request named "chore(release): X.X.X" review and merge it with "Rebase and merge" (or "Squash and merge")
1. After merge release action will be triggered automatically
1. Navigate to Repo => Actions and see last actions logs for further details 