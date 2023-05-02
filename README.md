# <img src="https://docs.lido.fi/img/logo.svg" alt="Lido" width="46"/> Lido Oracle

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Tests](https://github.com/lidofinance/lido-oracle/workflows/Tests/badge.svg?branch=daemon_v2)](https://github.com/lidofinance/lido-oracle/actions)

Oracle daemon for Lido decentralized staking service: Monitoring the state of the protocol across both layers and submitting regular update reports to the Lido smart contracts.

## How it works

There are two modules in the oracle:

- Accounting
- Ejector

### Accounting module

Accounting module updates the protocol TVL, distributes node-operator rewards, updates information about the number of exited and stuck validators and processes user withdrawal requests.
Also Accounting module makes decision to turn on/off the bunker. 

**Flow**

The oracle work is delineated by time periods called frames. Oracles finalize a report in each frame.
The default Accounting Oracle frame length on mainnet is 225 epochs, which is 24 hours (it could be changed by DAO). 
The frame includes these stages:

- **Waiting** - oracle starts as daemon and wakes up every 12 seconds (by default) in order to find the last finalized slot (ref slot).
  If ref slot missed, Oracle tries to find previous non-missed slot.
- **Data collection**: oracles monitor the state of both the execution and consensus layers and collect the data;
- **Hash consensus**: oracles analyze the data, compile the report and submit its hash to the HashConsensus smart contract;
- **Core update report**: once the quorum of hashes is reached, meaning required number of Oracles submitted the same hash,
  one of the oracles chosen in turn submits the actual report to the AccountingOracle contract, which triggers the core protocol
  state update, including the token rebase, finalization of withdrawal requests, and
  deciding whether to go in the bunker mode.
- **Extra data report**: an additional report carrying additional information. This part is required.
  All node operators rewards are distributed in this phase.

### Ejector module

Ejector module requests Lido validators to eject via events in Execution Layer when the protocol requires additional funds to process user withdrawals.

**Flow**

- Finds out how much ETH is needed to cover withdrawals.
- Predicts mean Lido income into Withdrawal and Execution Rewards Vaults.
- Figures out when the next validator will be withdrawn.
- Encode Lido validators to eject int bytes and send transaction.

# Usage

## Machine requirements

- vCPUs - 2
- Memory - 8 GB

## Dependencies

### Execution Client Node

To prepare the report, Oracle fetches up to 10 days old events, makes historical requests for balance data and makes simulated reports on historical blocks. This requires an [archive](https://ethereum.org/en/developers/docs/nodes-and-clients/#archive-node) execution node.
Oracle needs two weeks of archived data.

| Client                                          | Tested | Notes                                                                                                                                                                           |
|-------------------------------------------------|--------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [Geth](https://geth.ethereum.org/)              |        |                                                                                                                                                                                 |
| [Nethermind](https://nethermind.io/)            |        |                                                                                                                                                                                 |
| [Besu](https://besu.hyperledger.org/en/stable/) |        | Use <br>`--rpc-max-logs-range=100000` <br> `--sync-mode=FULL` <br> `--data-storage-format="FOREST"` <br> `--pruning-enabled` <br>`--pruning-blocks-retained=100000` <br> params |
| [Erigon](https://github.com/ledgerwatch/erigon) |        | Use <br> `--prune=htc` <br> `--prune.h.before=100000` <br> `--prune.t.before=100000` <br> `--prune.c.before=100000` <br> params                                                 |

### Consensus Client Node

Also, to calculate some metrics for bunker mode Oracle needs [archive](https://ethereum.org/en/developers/docs/nodes-and-clients/#archive-node) consensus node.

| Client                                            | Tested | Notes                                                                                                                                           |
|---------------------------------------------------|--------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| [Lighthouse](https://lighthouse.sigmaprime.io/)   |        | Use `--reconstruct-historic-states` param                                                                                                       |
| [Lodestar](https://nethermind.io/)                |        |                                                                                                                                                 |
| [Nimbus](https://besu.hyperledger.org/en/stable/) |        |                                                                                                                                                 |
| [Prysm](https://github.com/ledgerwatch/erigon)    |        | Use <br> `--grpc-max-msg-size=104857600` <br> `--enable-historical-state-representation=true` <br> `--slots-per-archive-point=1024` <br> params |
| [Teku](https://docs.teku.consensys.net)           |        | Use <br> `--data-storage-mode=archive` <br>`--data-storage-archive-frequency=1024`<br> `--reconstruct-historic-states=true`<br> params          |

### Keys API Service

This is a separate service that uses execution client to fetch all Lido keys. It stores the latest state of Lido keys in database.

[Keys API repository](https://github.com/lidofinance/lido-keys-api).

## Setup

Oracle daemon could be run using a docker container. Images is available on [Docker Hub](https://hub.docker.com/r/lidofinance/oracle).
Pull the image using the following command:

```bash
docker pull lidofinance/oracle:{tag}
```

Where `{tag}` is a version of the image. You can find the latest version in the [releases](https://github.com/lidofinance/lido-oracle/releases)
**OR**\
You can build it locally using the following command (make sure build it from latest [release](https://github.com/lidofinance/lido-oracle/releases)):

```bash
docker build -t lidofinance/oracle .
```

Full variables list could be found [here](https://github.com/lidofinance/lido-oracle#env-variables).

## Checks before running

1. Use [.env.example](.env.example) file content to create your own `.env` file.
   Set required values. It will be enough to run the oracle in _check mode_.
2. Check that your environment is ready to run the oracle using the following command:
   ```bash
   docker run -ti --env-file .env --rm lidofinance/oracle:{tag} check
   ```
   If everything is ok, you will see that all required checks are passed
   and your environment is ready to run the oracle.

## Run the oracle
1. By default, the oracle runs in *dry mode*. It means that it will not send any transactions to the Ethereum network.
    To run Oracle in *production mode*, set `MEMBER_PRIV_KEY` or `MEMBER_PRIV_KEY_FILE` environment variable:
    ```
    MEMBER_PRIV_KEY={value}
    ```
    Where `{value}` is a private key of the Oracle member account or:
    ```
    MEMBER_PRIV_KEY_FILE={path}
    ```
    Where `{path}` is a path to the private key of the Oracle member account.
2. Run the container using the following command:

   ```bash
   docker run --env-file .env lidofinance/oracle:{tag} {type}
   ```

   Replace `{tag}` with the image version and `{type}` with one of the two types of oracles: accounting or ejector.

> **Note**: of course, you can pass env variables without using `.env` file.
> For example, you can run the container using the following command:
>
> ```bash
> docker run --env EXECUTION_CLIENT_URI={value} --env CONSENSUS_CLIENT_URI={value} --env KEYS_API_URI={value} --env LIDO_LOCATOR_ADDRESS={value} lidofinance/oracle:{tag} {type}
> ```

## Manual mode

Oracle could be executed once in "manual" mode. To do this setup `DAEMON` variable to 'False'.

**Note**: Use `-it` option to run manual mode in Docker container in interactive mode.  
Example `docker run -ti --env-file .env --rm lidofinance/oracle:{tag} {type}`

In this mode Oracle will build report as usual (if contracts are reportable) and before submitting transactions
Oracle will ask for manual input to send transaction.

In manual mode all sleeps are disabled and `ALLOW_REPORTING_IN_BUNKER_MODE` is True. 

## Env variables

| Name                                                   | Description                                                                                                                                                              | Required | Example value           |
|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|-------------------------|
| `EXECUTION_CLIENT_URI`                                 | URI of the Execution Layer client                                                                                                                                        | True     | `http://localhost:8545` |
| `CONSENSUS_CLIENT_URI`                                 | URI of the Consensus Layer client                                                                                                                                        | True     | `http://localhost:5052` |
| `KEYS_API_URI`                                         | URI of the Keys API                                                                                                                                                      | True     | `http://localhost:8080` |
| `LIDO_LOCATOR_ADDRESS`                                 | Address of the Lido contract                                                                                                                                             | True     | `0x1...`                |
| `MEMBER_PRIV_KEY`                                      | Private key of the Oracle member account                                                                                                                                 | False    | `0x1...`                |
| `MEMBER_PRIV_KEY_FILE`                                 | A path to the file contained the private key of the Oracle member account. It takes precedence over `MEMBER_PRIV_KEY`                                                    | False    | `/app/private_key`      |
| `FINALIZATION_BATCH_MAX_REQUEST_COUNT`                 | The size of the batch to be finalized per request (The larger the batch size, the more memory of the contract is used but the fewer requests are needed)                 | False    | `1000`                  |
| `ALLOW_REPORTING_IN_BUNKER_MODE`                       | Allow the Oracle to do report if bunker mode is active                                                                                                                   | False    | `True`                  |
| `DAEMON`                                               | If False Oracle runs one cycle and ask for manual input to send report.                                                                                                  | False    | `True`                  |
| `TX_GAS_ADDITION`                                      | Used to modify gas parameter that used in transaction. (gas = estimated_gas + TX_GAS_ADDITION)                                                                           | False    | `100000`                |
| `CYCLE_SLEEP_IN_SECONDS`                               | The time between cycles of the oracle's activity                                                                                                                         | False    | `12`                    |
| `SUBMIT_DATA_DELAY_IN_SLOTS`                           | The difference in slots between submit data transactions from Oracles. It is used to prevent simultaneous sending of transactions and, as a result, transactions revert. | False    | `6`                     |
| `HTTP_REQUEST_TIMEOUT_EXECUTION`                       | Timeout for HTTP execution layer requests                                                                                                                                | False    | `120`                   |
| `HTTP_REQUEST_TIMEOUT_CONSENSUS`                       | Timeout for HTTP consensus layer requests                                                                                                                                | False    | `300`                   |
| `HTTP_REQUEST_RETRY_COUNT_CONSENSUS`                   | Total number of retries to fetch data from endpoint for consensus layer requests                                                                                         | False    | `5`                     |
| `HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS` | The delay http provider sleeps if API is stuck for consensus layer                                                                                                       | False    | `12`                    |
| `HTTP_REQUEST_TIMEOUT_KEYS_API`                        | Timeout for HTTP keys api requests                                                                                                                                       | False    | `10`                    |
| `HTTP_REQUEST_RETRY_COUNT_KEYS_API`                    | Total number of retries to fetch data from endpoint for keys api requests                                                                                                | False    | `300`                   |
| `HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API`  | The delay http provider sleeps if API is stuck for keys api                                                                                                              | False    | `300`                   |
| `PRIORITY_FEE_PERCENTILE`                              | Priority fee percentile from prev block that would be used to send tx                                                                                                    | False    | `3`                     |
| `MIN_PRIORITY_FEE`                                     | Min priority fee that would be used to send tx                                                                                                                           | False    | `50000000`              |
| `MAX_PRIORITY_FEE`                                     | Max priority fee that would be used to send tx                                                                                                                           | False    | `100000000000`          |


### Alerts

A few basic alerts, which can be configured in the [Prometheus Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/).

```yaml
groups:
  - name: oracle-alerts
    rules:
      - alert: AccountBalance
        expr: lido_oracle_account_balance / 10^18 < 1
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Dangerously low account balance"
          description: "Account balance is less than 1 ETH. Address: {.labels.address}: {.value} ETH"
      - alert: OutdatedData
        expr: (lido_oracle_genesis_time + ignoring (state) lido_oracle_slot_number{state="head"} * 12) < time() - 300
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "Outdated Consensus Layer HEAD slot"
          description: "Processed by Oracle HEAD slot {.value} too old"
```

### Metrics

> **Note**: all metrics are prefixed with `lido_oracle_` by default.

The oracle exposes the following basic metrics:

| Metric name                 | Description                                                     | Labels                                                                                             |
|-----------------------------|-----------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| build_info                  | Build info                                                      | version, branch, commit                                                                            |
| env_variables_info          | Env variables for the app                                       | ACCOUNT, LIDO_LOCATOR_ADDRESS, FINALIZATION_BATCH_MAX_REQUEST_COUNT, MAX_CYCLE_LIFETIME_IN_SECONDS |
| genesis_time                | Fetched genesis time from node                                  |                                                                                                    |
| account_balance             | Fetched account balance from EL                                 | address                                                                                            |
| slot_number                 | Last fetched slot number from CL                                | state (`head` or `finalized`)                                                                      |
| block_number                | Last fetched block number from CL                               | state (`head` or `finalized`)                                                                      |
| functions_duration          | Histogram metric with duration of each main function in the app | name, status                                                                                       |
| el_requests_duration        | Histogram metric with duration of each EL request               | endpoint, call_method, call_to, code, domain                                                       |
| cl_requests_duration        | Histogram metric with duration of each CL request               | endpoint, code, domain                                                                             |
| keys_api_requests_duration  | Histogram metric with duration of each KeysAPI request          | endpoint, code, domain                                                                             |
| keys_api_latest_blocknumber | Latest block number from KeysAPI metadata                       |                                                                                                    |
| transaction_count           | Total count of transactions. Success or failure                 | status                                                                                             |
| member_info                 | Oracle member info                                              | is_report_member, is_submit_member, is_fast_lane                                                   |
| member_last_report_ref_slot | Member last report ref slot                                     |                                                                                                    |
| frame_current_ref_slot      | Current frame ref slot                                          |                                                                                                    |
| frame_deadline_slot         | Current frame deadline slot                                     |                                                                                                    |
| frame_prev_report_ref_slot  | Previous report ref slot                                        |                                                                                                    |
| contract_on_pause           | Contract on pause                                               |                                                                                                    |

Special metrics for accounting oracle:

| Metric name                             | Description                                         | Labels           |
|-----------------------------------------|-----------------------------------------------------|------------------|
| accounting_is_bunker                    | Is bunker mode enabled                              |                  |
| accounting_cl_balance_gwei              | Reported CL balance in gwei                         |                  |
| accounting_el_rewards_vault_wei         | Reported EL rewards in wei                          |                  |
| accounting_withdrawal_vault_balance_wei | Reported withdrawal vault balance in wei            |                  |
| accounting_exited_validators            | Reported exited validators count for each operator  | module_id, no_id |
| accounting_stuck_validators             | Reported stuck validators count for each operator   | module_id, no_id |
| accounting_delayed_validators           | Reported delayed validators count for each operator | module_id, no_id |

Special metrics for ejector oracle:

| Metric name                       | Description                                 | Labels |
|-----------------------------------|---------------------------------------------|--------|
| ejector_withdrawal_wei_amount     | To withdraw amount                          |        |
| ejector_max_exit_epoch            | Max exit epoch between all validators in CL |        |
| ejector_validators_count_to_eject | Validators count to eject                   |        |

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
- `check`

## Tests

[Testing guide](./tests/README.md)

```bash
poetry run pytest .
```

## Code quality

Used the following tools:

- [black](https://github.com/psf/black)
- [pylint](https://github.com/pylint-dev/pylint/)
- [mypy](https://github.com/python/mypy/)
  See the [configuration](pyproject.toml) for details for each linter.

Make sure that your code is formatted correctly and passes all checks:

```bash
black tests
pylint src tests
mypy src
```

# License

2023 Lido <info@lido.fi>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License, or any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
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
