# <img src="docs/logo.svg" height="70px" align="center" alt="Lido Logo"/> Lido Oracle

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Oracle daemon for Lido decentralized staking service: Monitoring the state of the protocol across both layers and submitting regular update reports to the Lido smart contracts.

## 🚀 Quick Start

```bash
# 1. Pull Docker image
docker pull lidofinance/oracle:{tag}

# 2. Prepare .env file
cp .env.example .env
# Edit .env with necessary values

# 3. Check environment
docker run -ti --env-file .env --rm lidofinance/oracle:{tag} check

# 4. Run the Oracle (dry mode by default)
docker run --env-file .env lidofinance/oracle:{tag} accounting  # | ejector | csm
```

Or checkout [Oracle Operator Manual](https://docs.lido.fi/guides/oracle-operator-manual) for more details.

## How it works

There are 3 modules in the oracle:

- Accounting (accounting)
- Valdiators Exit Bus (ejector)
- CSM (csm)

### Accounting module

Handles protocol TVL updates, node operator rewards, validator status, withdrawal requests, and bunker mode toggling.

**Flow**

Work is divided into frames (~24 hours / 225 epochs):
- **Waiting**: Oracle daemon wakes up every 12s, fetches the latest finalized slot, and waits until a new frame begins.
- **Data collection**: Gathers state data from Execution and Consensus layers.
- **Hash consensus**: Hash of report is submitted to the HashConsensus contract.
- **Core update report**: Once quorum is reached, actual report is submitted to AccountingOracle to trigger state updates (rebases, withdrawals, bunker check).
- **Extra data report**: Multi-transactional report for exited validators, reward unlocking, etc.

### Ejector module

Initiates validator ejection requests to fund withdrawal requests using a specific order defined in `src/services/exit_order_interator.py`.

**Flow**

Work is divided into frames (~8 hours / 75 epochs):
- Calculates ETH required for withdrawals.
- Estimates incoming ETH to protocol.
- Determines next available validator exit.
- Builds validators to exit queue and submits data to Execution Layer.

### CSM module

Collects and reports validator attestation rate for node operators. Handles publishing metadata to IPFS for the CSM.

Work is divided into frames (~28 days / 6300 epochs):
- **Data collection**: Processes new epoches and collect attestations.
- **IPFS data submittion**: Uploads report and full logs to IPFS.
- **Update report**: Submits report to the CSFeeOracle contract.

# Usage

## Machine requirements

For each Oracle module:
- vCPUs - 1
- Memory - 8 GB

[KAPI](https://github.com/lidofinance/lido-keys-api):
- vCPU - 2
- Memory - 8 GB

## Dependencies

### Execution Client Node

Requires an [archive](https://ethereum.org/en/developers/docs/nodes-and-clients/#archive-node) node with 2 weeks of history.

| Client                                          | Tested | Notes                                                                                                                                                                           |
|-------------------------------------------------|:------:|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [Geth](https://geth.ethereum.org/)              |   🟢   | `--gcmode=archive` <br> `--syncmode=snap` <br><br>OR<br><br>`--gcmode=archive`<br>`--syncmode=full`                                                                             |
| [Nethermind](https://nethermind.io/)            |   🔴   | Not tested yet                                                                                                                                                                  |
| [Besu](https://besu.hyperledger.org/en/stable/) |   🟢   | Use <br>`--rpc-max-logs-range=100000` <br> `--sync-mode=FULL` <br> `--data-storage-format="FOREST"` <br> `--pruning-enabled` <br>`--pruning-blocks-retained=100000` <br> params |
| [Erigon](https://github.com/ledgerwatch/erigon) |   🟢   | Use <br> `--prune=htc` <br> `--prune.h.before=100000` <br> `--prune.t.before=100000` <br> `--prune.c.before=100000` <br> params                                                 |
| [Reth](https://reth.rs/)                        |   🔴   | Not tested yet                                                                                                                                                                  |

### Consensus Client Node

Also, to calculate some metrics for bunker mode Oracle needs [archive](https://ethereum.org/en/developers/docs/nodes-and-clients/#archive-node) consensus node.

| Client                                          | Tested | Notes                                                                                                                                           |
|-------------------------------------------------|:------:|-------------------------------------------------------------------------------------------------------------------------------------------------|
| [Lighthouse](https://lighthouse.sigmaprime.io/) |   🟢   | Use `--reconstruct-historic-states` param                                                                                                       |
| [Lodestar](https://lodestar.chainsafe.io)       |   🔴   | Not tested yet                                                                                                                                  |
| [Nimbus](https://nimbus.team)                   |   🔴   | Not tested yet                                                                                                                                  |
| [Prysm](https://github.com/prysmaticlabs/prysm) |   🟢   | Use <br> `--grpc-max-msg-size=104857600` <br> `--enable-historical-state-representation=true` <br> `--slots-per-archive-point=1024` <br> params |
| [Teku](https://docs.teku.consensys.net)         |   🟢   | Use <br> `--data-storage-mode=archive` <br>`--data-storage-archive-frequency=1024`<br> `--reconstruct-historic-states=true`<br> params          |
| [Grandine](https://docs.grandine.io/)           |   🔴   | Not tested yet                                                                                                                                  |

### Keys API Service

Separate service to collect and store validator keys from clients. [Lido Keys API repository.](https://github.com/lidofinance/lido-keys-api)

## Setup

Oracle daemon could be run using a docker container. Images is available on [Docker Hub](https://hub.docker.com/r/lidofinance/oracle).
Pull the image using the following command:

```bash
docker pull lidofinance/oracle:{tag}
```

Where `{tag}` is a version of the image. You can find the latest version in the [releases](https://github.com/lidofinance/lido-oracle/releases)\
**OR** You can build it locally using the following command (make sure build it from latest [release](https://github.com/lidofinance/lido-oracle/releases)):

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

| Name                                                   | Description                                                                                                                                                              | Required | Example value                  |
|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|--------------------------------|
| `EXECUTION_CLIENT_URI`                                 | URI of the Execution Layer client                                                                                                                                        | True     | `http://localhost:8545`        |
| `CONSENSUS_CLIENT_URI`                                 | URI of the Consensus Layer client                                                                                                                                        | True     | `http://localhost:5052`        |
| `KEYS_API_URI`                                         | URI of the Keys API                                                                                                                                                      | True     | `http://localhost:8080`        |
| `LIDO_LOCATOR_ADDRESS`                                 | Address of the Lido contract                                                                                                                                             | True     | `0x1...`                       |
| `CSM_MODULE_ADDRESS`                                   | Address of the CSModule contract                                                                                                                                         | CSM only | `0x1...`                       |
| `MEMBER_PRIV_KEY`                                      | Private key of the Oracle member account                                                                                                                                 | False    | `0x1...`                       |
| `MEMBER_PRIV_KEY_FILE`                                 | A path to the file contained the private key of the Oracle member account. It takes precedence over `MEMBER_PRIV_KEY`                                                    | False    | `/app/private_key`             |
| `PINATA_JWT`                                           | JWT token to access pinata.cloud IPFS provider                                                                                                                           | True     | `aBcD1234...`                  |
| `PINATA_JWT_FILE`                                      | A path to a file with a JWT token to access pinata.cloud IPFS provider                                                                                                   | True     | `/app/pintata_secret`          |
| `PINATA_DEDICATED_GATEWAY_URL`                         | URL of the dedicated Pinata gateway (required for Pinata provider, fallback to public gateway if dedicated fails)                                                        | CSM only | `https://gateway.pinata.cloud` |
| `PINATA_DEDICATED_GATEWAY_TOKEN`                       | Token for accessing dedicated Pinata gateway (required for Pinata provider)                                                                                              | CSM only | `gAT_abc123...`                |
| `STORACHA_AUTH_SECRET`                                 | Secret for Storacha IPFS provider                                                                                                                                        | True     | `uMGVabc...`                   |
| `STORACHA_AUTHORIZATION`                               | Authorization for Storacha IPFS provider                                                                                                                                 | True     | `uMGVabc...`                   |
| `STORACHA_SPACE_DID`                                   | Space DID for Storacha IPFS provider                                                                                                                                     | True     | `did:key:z6Mkabc...`           |
| `LIDO_IPFS_HOST`                                       | Host to access Lido IPFS cluster                                                                                                                                         | True     | `https://ipfs.lido.fi`         |
| `LIDO_IPFS_TOKEN`                                      | Bearer token for Lido IPFS cluster authentication                                                                                                                        | True     | `eyJhbG...`                    |
| `KUBO_HOST`                                            | Host to access running Kubo IPFS node                                                                                                                                    | False    | `localhost`                    |
| `KUBO_RPC_PORT`                                        | Port to access RPC provided by Kubo IPFS node                                                                                                                            | False    | `5001`                         |
| `KUBO_GATEWAY_PORT`                                    | Port to access gateway provided by Kubo IPFS node                                                                                                                        | False    | `8080`                         |
| `FINALIZATION_BATCH_MAX_REQUEST_COUNT`                 | The size of the batch to be finalized per request (The larger the batch size, the more memory of the contract is used but the fewer requests are needed)                 | False    | `1000`                         | 
| `EL_REQUESTS_BATCH_SIZE`                               | The amount of entities that would be fetched in one request to EL                                                                                                        | False    | `1000`                         | 
| `ALLOW_REPORTING_IN_BUNKER_MODE`                       | Allow the Oracle to do report if bunker mode is active                                                                                                                   | False    | `True`                         |
| `DAEMON`                                               | If False Oracle runs one cycle and ask for manual input to send report.                                                                                                  | False    | `True`                         |
| `TX_GAS_ADDITION`                                      | Used to modify gas parameter that used in transaction. (gas = estimated_gas + TX_GAS_ADDITION)                                                                           | False    | `100000`                       |
| `CYCLE_SLEEP_IN_SECONDS`                               | The time between cycles of the oracle's activity                                                                                                                         | False    | `12`                           |
| `MAX_CYCLE_LIFETIME_IN_SECONDS`                        | The maximum time for a cycle to continue                                                                                                                                 | False    | `3000`                         |
| `SUBMIT_DATA_DELAY_IN_SLOTS`                           | The difference in slots between submit data transactions from Oracles. It is used to prevent simultaneous sending of transactions and, as a result, transactions revert. | False    | `6`                            |
| `HTTP_REQUEST_TIMEOUT_EXECUTION`                       | Timeout for HTTP execution layer requests                                                                                                                                | False    | `120`                          |
| `HTTP_REQUEST_TIMEOUT_CONSENSUS`                       | Timeout for HTTP consensus layer requests                                                                                                                                | False    | `300`                          |
| `HTTP_REQUEST_RETRY_COUNT_CONSENSUS`                   | Total number of retries to fetch data from endpoint for consensus layer requests                                                                                         | False    | `5`                            |
| `HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS` | The delay http provider sleeps if API is stuck for consensus layer                                                                                                       | False    | `12`                           |
| `HTTP_REQUEST_TIMEOUT_KEYS_API`                        | Timeout for HTTP keys api requests                                                                                                                                       | False    | `120`                          |
| `HTTP_REQUEST_RETRY_COUNT_KEYS_API`                    | Total number of retries to fetch data from endpoint for keys api requests                                                                                                | False    | `300`                          |
| `HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API`  | The delay http provider sleeps if API is stuck for keys api                                                                                                              | False    | `300`                          |
| `HTTP_REQUEST_TIMEOUT_IPFS`                            | Timeout for HTTP requests to an IPFS provider                                                                                                                            | False    | `30`                           |
| `HTTP_REQUEST_RETRY_COUNT_IPFS`                        | Total number of retries to fetch data from an IPFS provider                                                                                                              | False    | `3`                            |
| `IPFS_VALIDATE_CID`                                    | Enable/disable CID validation for IPFS operations                                                                                                                        | False    | `True`                         |
| `EVENTS_SEARCH_STEP`                                   | Maximum length of a range for eth_getLogs method calls                                                                                                                   | False    | `10000`                        |
| `PRIORITY_FEE_PERCENTILE`                              | Priority fee percentile from prev block that would be used to send tx                                                                                                    | False    | `3`                            |
| `MIN_PRIORITY_FEE`                                     | Min priority fee that would be used to send tx                                                                                                                           | False    | `50000000`                     |
| `MAX_PRIORITY_FEE`                                     | Max priority fee that would be used to send tx                                                                                                                           | False    | `100000000000`                 |
| `CSM_ORACLE_MAX_CONCURRENCY`                           | Max count of dedicated workers for CSM module                                                                                                                            | False    | `2`                            |
| `CACHE_PATH`                                           | Directory to store cache for CSM module                                                                                                                                  | False    | `.`                            |
| `OPSGENIE_API_KEY`                                     | OpsGenie API key for authentication with the OpsGenie API. Used to send alerts from lido-oracle health-checks.                                                           | False    | `<api-key>`                    |
| `OPSGENIE_API_URL`                                     | Base URL for the OpsGenie API.                                                                                                                                           | False    | `http://localhost:8080`        |
| `VAULT_PAGINATION_LIMIT`                               | The limit for getting staking vaults with pagination. Default 1000                                                                                                       | False    | `1000`                         |
| `VAULT_VALIDATOR_STAGES_BATCH_SIZE`                    | The limit for getting validators stages in one request. Default 100                                                                                                      | False    | `100`                          |

### Mainnet variables
> LIDO_LOCATOR_ADDRESS=0xC1d0b3DE6792Bf6b4b37EccdcC24e45978Cfd2Eb
> CSM_MODULE_ADDRESS=0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F
> ALLOW_REPORTING_IN_BUNKER_MODE=False

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

| Metric name                 | Description                                                     | Labels                                                                                                                                         |
|-----------------------------|-----------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| build_info                  | Build info                                                      | version, branch, commit                                                                                                                        |
| env_variables_info          | Env variables for the app                                       | ACCOUNT, LIDO_LOCATOR_ADDRESS, CSM_MODULE_ADDRESS, FINALIZATION_BATCH_MAX_REQUEST_COUNT, EL_REQUESTS_BATCH_SIZE, MAX_CYCLE_LIFETIME_IN_SECONDS |
| genesis_time                | Fetched genesis time from node                                  |                                                                                                                                                |
| account_balance             | Fetched account balance from EL                                 | address                                                                                                                                        |
| slot_number                 | Last fetched slot number from CL                                | state (`head` or `finalized`)                                                                                                                  |
| block_number                | Last fetched block number from CL                               | state (`head` or `finalized`)                                                                                                                  |
| functions_duration          | Histogram metric with duration of each main function in the app | name, status                                                                                                                                   |
| cl_requests_duration        | Histogram metric with duration of each CL request               | endpoint, code, domain                                                                                                                         |
| keys_api_requests_duration  | Histogram metric with duration of each KeysAPI request          | endpoint, code, domain                                                                                                                         |
| keys_api_latest_blocknumber | Latest block number from KeysAPI metadata                       |                                                                                                                                                |
| transactions_count          | Total count of transactions. Success or failure                 | status                                                                                                                                         |
| member_info                 | Oracle member info                                              | is_report_member, is_submit_member, is_fast_lane                                                                                               |
| member_last_report_ref_slot | Member last report ref slot                                     |                                                                                                                                                |
| frame_current_ref_slot      | Current frame ref slot                                          |                                                                                                                                                |
| frame_deadline_slot         | Current frame deadline slot                                     |                                                                                                                                                |
| frame_prev_report_ref_slot  | Previous report ref slot                                        |                                                                                                                                                |
| contract_on_pause           | Contract on pause                                               |                                                                                                                                                |

Interaction with external providers:

| Metric name                     | Description                                                                           | Labels                                                             |
|---------------------------------|---------------------------------------------------------------------------------------|--------------------------------------------------------------------|
| http_rpc_requests_total         | Counts total HTTP requests used by any layer                                          | network, layer, chain_id, provider, batched, response_code, result |
| http_rpc_batch_size             | Distribution of how many JSON-RPC calls (or similar) are bundled in each HTTP request | network, layer, chain_id, provider                                 |
| http_rpc_response_seconds       | Distribution of RPC response times                                                    | network, layer, chain_id, provider                                 |
| http_rpc_request_payload_bytes  | Distribution of request payload sizes (bytes) RPC calls                               | network, layer, chain_id, provider                                 |
| http_rpc_response_payload_bytes | Distribution of response payload sizes (bytes) RPC calls                              | network, layer, chain_id, provider                                 |
| rpc_request_total               | Distribution of response payload sizes (bytes) RPC calls                              | network, layer, chain_id, provider, method, result, rpc_error_code |

Special metrics for accounting oracle:

| Metric name                             | Description                                         | Labels           |
|-----------------------------------------|-----------------------------------------------------|------------------|
| accounting_is_bunker                    | Is bunker mode enabled                              |                  |
| accounting_cl_balance_gwei              | Reported CL balance in gwei                         |                  |
| accounting_el_rewards_vault_wei         | Reported EL rewards in wei                          |                  |
| accounting_withdrawal_vault_balance_wei | Reported withdrawal vault balance in wei            |                  |
| accounting_exited_validators            | Reported exited validators count for each operator  | module_id, no_id |

Special metrics for ejector oracle:

| Metric name                       | Description                                          | Labels |
|-----------------------------------|------------------------------------------------------|--------|
| ejector_withdrawal_wei_amount     | To withdraw amount                                   |        |
| ejector_max_withdrawal_epoch      | Max withdrawal epoch among all Lido validators on CL |        |
| ejector_validators_count_to_eject | Validators count to eject                            |        |

Special metrics for CSM oracle:

| Metric name                     | Description                            | Labels |
|---------------------------------|----------------------------------------|--------|
| csm_current_frame_range_l_epoch | Left epoch of the current frame range  |        |
| csm_current_frame_range_r_epoch | Right epoch of the current frame range |        |
| csm_unprocessed_epochs_count    | Unprocessed epochs count               |        |
| csm_min_unprocessed_epoch       | Minimum unprocessed epoch              |        |

# Development

## Setup
Check out our [development setup guide](docs/development.md).

## Release flow

To create new release:

1. Merge all changes to the `master` branch
1. Navigate to Repo => Actions
1. Run action "Prepare release" action against `master` branch
1. When action execution is finished, navigate to Repo => Pull requests
1. Find pull request named "chore(release): X.X.X" review and merge it with "Rebase and merge" (or "Squash and merge")
1. After merge release action will be triggered automatically
1. Navigate to Repo => Actions and see last actions logs for further details

## Reproducible builds

The Lido Oracle supports reproducible Docker builds in experimental mode. Check out [guide](docs/reproducible-builds.md) for more details.

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