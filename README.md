# Lido-Oracle daemon

[![Tests](https://github.com/lidofinance/lido-oracle/workflows/Tests/badge.svg?branch=daemon_v2)](https://github.com/lidofinance/lido-oracle/actions)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Oracle daemon for [Lido](https://lido.fi) decentralized staking service. Collects and reports Beacon Chain states (the number of visible validators and their summarized balances) to the Lido dApp contract running on Ethereum 1.0 side.

## How it works

* Upon the start daemon determines the reportable epoch and retrieves the list of validator keys to watch for.

* Then it Gets the Lido-controlled validators from the reportable beacon state and summarizes their balances.

* Constructs the transaction containing the `epochId`, `beaconBalance`, and `beaconValidators`.

* If the daemon has `MEMBER_PRIV_KEY` in its environment (i.e. isn't running in dry-run mode), it signs and sends the transaction to the oracle contract (asking for user confirmation if running interactively).

* If the oracle runs in the daemon mode (with `DAEMON=1` env ) it waits `SLEEP` seconds and restarts the loop.

## Setup

The oracle daemon requires fully-synced ETH1.0 and Beacon nodes. We highly recommend using
[geth](https://geth.ethereum.org/docs/install-and-build/installing-geth#run-inside-docker-container) and
[Lighthouse](https://lighthouse-book.sigmaprime.io/docker.html#using-the-docker-image).

Note: Prysm beacon client is also supported (use with `--grpc-max-msg-size=104857600` param).

```sh
docker run -d --name geth -v $HOME/.geth:/root -p 30303:30303 -p 8545:8545 ethereum/client-go --http --http.addr=0.0.0.0
docker run -d --name lighthouse -v $HOME/.ligthouse:/root/.lighthouse  -p 9000:9000 -p 5052:5052 sigp/lighthouse lighthouse beacon --http --http-address 0.0.0.0
```

## Run

The oracle receives its configuration via Environment variables. You need to provide URIs of both nodes and the Lido contract address. The following snippet (adapted to your setup) will start the oracle in safe, read-only mode called **Dry-run**. It will run the single loop iteration, calculate the report and print it out instead of sending real TX.

```sh
export WEB3_PROVIDER_URI=$ETH1_NODE_RPC_ADDRESS
export BEACON_NODE=$BEACON_CHAIN_NODE_RPC_ADDRESS
export MEMBER_PRIV_KEY=$ORACLE_PRIVATE_KEY_0X_PREFIXED
export POOL_CONTRACT=0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84
export STETH_PRICE_ORACLE_CONTRACT=0x3a6bd15abf19581e411621d669b6a2bbe741ffd6
export STETH_CURVE_POOL_CONTRACT=0xDC24316b9AE028F1497c275EB9192a3Ea0f67022
export DAEMON=0
export ORACLE_FROM_BLOCK=11595281
export CONSIDER_WITHDRAWALS_FROM_EPOCH=191900
docker run -e WEB3_PROVIDER_URI -e BEACON_NODE -e POOL_CONTRACT -e DAEMON -e ORACLE_FROM_BLOCK -it lidofinance/oracle:2.5.0
```

Other pre-built oracle images can be found in the [Lido dockerhub](https://hub.docker.com/r/lidofinance/oracle/tags?page=1&ordering=last_updated).

See **Other examples** below for transactable modes.

## Full list of configuration options

* `WEB3_PROVIDER_URI` - HTTP or WS URL of web3 Ethereum node (tested with Geth). You can use multiply ETH1 endpoints separated with comma. (e.g. `http://example.com,wss://127.0.0.1:9000`)**Required**.
* `BEACON_NODE` - HTTP endpoint of Beacon Node (Lighthouse recommended, also tested with Prysm). **Required**.
* `POOL_CONTRACT` - Lido contract in EIP-55 (mixed-case) hex format. **Required**. Example: `0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84`
* `STETH_CURVE_POOL_CONTRACT` - address of Curve ETH/stETH stable swap pool. If provided together with `STETH_PRICE_ORACLE_CONTRACT` stETH price oracle will be enabled.
* `STETH_PRICE_ORACLE_CONTRACT` - address of Lido's stable swap state oracle. If provided together with `STETH_CURVE_POOL_CONTRACT` stETH price oracle will be enabled.
* `STETH_PRICE_ORACLE_BLOCK_NUMBER_SHIFT` - indent from `latest` block number to be used in computation of new state for stable swap. **Optional**. Default: `15`
* `DAEMON` - with `DAEMON=0` runs the single iteration then quits. `DAEMON=0` in combination with `MEMBER_PRIV_KEY` runs interactively and asks user for confirmation before sending each TX. With `DAEMON=1` runs autonomously (without confirmation) in an indefinite loop. **Optional**. Default: `0`
* `MEMBER_PRIV_KEY` - Hex-encoded private key of Oracle Quorum Member address. **Optional**. If omitted, the oracle runs in read-only (dry-run) mode. WARNING: Keep `MEMBER_PRIV_KEY` safe. Since it keeps real Ether to pay gas, it should never be exposed outside.
* `FORCE_DO_NOT_USE_IN_PRODUCTION` - **Do not use in production!** The oracle makes the sanity checks on the collected data before reporting. Running in `DAEMON` mode, if data look suspicious, it skips sending TX. In enforced mode it gets reported even if it looks suspicious.
   It's unsafe and used for smoke testing purposes, NEVER use it in production!  **Optional**. Default: `0`
* `SLEEP` seconds - The interval between iterations in Daemon mode. Default value: 60 s. Effective with `DAEMON=1` only.
* `GAS_LIMIT` - The pre-defined gasLimit for composed transaction. Defaulf value: 1 500 000. Effective in transactable mode (with given `MEMBER_PRIV_KEY`)
* `ORACLE_FROM_BLOCK` - The earlist block to check for oracle events. Needed on mainnet first run to skip 5 minutes of scanning blockchain for events that are not there, recommended to be set to 11595281 on mainnet deployments
* `CONSIDER_WITHDRAWALS_FROM_EPOCH` - The epoch from which withdrawals are considered.
* `PROMETHEUS_PREFIX` - Prefix for all prometheus metrics. This is good practice having different prefixes for applications (recommended to use `lido_oracle_`) **Optional**. Default ''
* `PROMETHEUS_METRICS_PORT` - Port for prometheus server. **Optional**. Default '8000'

## Other examples

* WARNING: The examples below are **transactable** and can potentially break the Lido. You must understand the protocol and what you are doing.
* WARNING: Keep your `MEMBER_PRIV_KEY` safe. Since it keeps real Ether to pay gas, it should never be exposed outside.
* WARNING: Never use the `MEMBER_PRIV_KEY` value given below. You will definitely lose all your Ethers if reuse that private key.

### Interactive supervised mode

This mode is intended for controlled start and allows to double-check the report and its effects before its actual sending. Runs the single iteration and asks for confirmation via interactive `[y/n]` prompt before sending real TX to the network. You should be connected (attached) to the terminal to see this.

```sh
export WEB3_PROVIDER_URI=$ETH1_NODE_RPC_ADDRESS
export BEACON_NODE=$BEACON_CHAIN_NODE_RPC_ADDRESS
export MEMBER_PRIV_KEY=$ORACLE_PRIVATE_KEY_0X_PREFIXED
export POOL_CONTRACT=0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84
export STETH_PRICE_ORACLE_CONTRACT=0x3a6bd15abf19581e411621d669b6a2bbe741ffd6
export STETH_CURVE_POOL_CONTRACT=0xDC24316b9AE028F1497c275EB9192a3Ea0f67022
export DAEMON=0
export ORACLE_FROM_BLOCK=11595281
export CONSIDER_WITHDRAWALS_FROM_EPOCH=191900
docker run -e WEB3_PROVIDER_URI -e BEACON_NODE -e POOL_CONTRACT -e DAEMON -e MEMBER_PRIV_KEY -e ORACLE_FROM_BLOCK -it lidofinance/oracle:2.5.0
```

### Autonomous mode

Runs in the background with 1-hour pauses between consecutive iterations. To be used without human supervision (on later stages).

```sh
export WEB3_PROVIDER_URI=$ETH1_NODE_RPC_ADDRESS
export BEACON_NODE=$BEACON_CHAIN_NODE_RPC_ADDRESS
export MEMBER_PRIV_KEY=$ORACLE_PRIVATE_KEY_0X_PREFIXED
export POOL_CONTRACT=0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84
export STETH_PRICE_ORACLE_CONTRACT=0x3a6bd15abf19581e411621d669b6a2bbe741ffd6
export STETH_CURVE_POOL_CONTRACT=0xDC24316b9AE028F1497c275EB9192a3Ea0f67022
export DAEMON=1
export SLEEP=300
export ORACLE_FROM_BLOCK=11595281
export CONSIDER_WITHDRAWALS_FROM_EPOCH=191900
docker run -e WEB3_PROVIDER_URI -e BEACON_NODE -e POOL_CONTRACT -e DAEMON -e MEMBER_PRIV_KEY -e SLEEP -e ORACLE_FROM_BLOCK lidofinance/oracle:2.5.0
```

## Build yourself

Instead of downloading the image from dockerhub, you can build it yourself. This requires git and python3.8+.

```sh
./build.sh
```

To build and push with the given version tag to the dockerhub:

```sh
TAG=0.1.3 PUSH=1 ./build.sh
```

## Prometheus metrics

Prometheus exporter is running on port 8000 and provides 5 logical groups of metrics.

### 1. Current status

Current Oracle daemon's state.

| name                                  | description                              | frequency                     | goal                                                                            |
|---------------------------------------|------------------------------------------|-------------------------------|---------------------------------------------------------------------------------|
| **reportableFrame** <br> *gauge*      | the report could be sent or is sending   |                               |                                                                                 |
| **nowEthV1BlockNumber**  <br> *gauge* | ETH1 latest block number                 | every COUNTDOWN_SLEEP seconds | should be increasing constantly and be aligned with https://etherscan.io/blocks |
| **daemonCountDown** <br> *gauge*      | time till the next oracle run in seconds | every COUNTDOWN_SLEEP seconds | should be decreasing down to 0                                                  |
| **finalizedEpoch** <br> *gauge*       | last finalized Beacon Chain epoch        | every COUNTDOWN_SLEEP seconds | should go up at a rate of 1 per six munites                                     |


### 2. Oracle process metrics

Oracle process stats.

| name                                               | description                                            | frequency           | goal                             |
|----------------------------------------------------|--------------------------------------------------------|---------------------|----------------------------------|
| **txSuccess**                     <br> *histogram* | number of successful transactions                      | every SLEEP seconds |                                  |
| **txRevert**                      <br> *histogram* | number of failed transactions                          | every SLEEP seconds |                                  |
| **process_virtual_memory_bytes**  <br> *gauge*     | Virtual memory size in bytes.                          | every call          | normal RAM consumption is ~200Mb |
| **process_resident_memory_bytes** <br> *gauge*     | Resident memory size in bytes.                         | every call          | normal RAM consumption is ~200Mb |
| **process_start_time_seconds**    <br> *gauge*     | Start time of the process since unix epoch in seconds. | every call          |                                  |
| **process_cpu_seconds_total**     <br> *counter*   | Total user and system CPU time spent in seconds.       | every call          |                                  |
| **process_open_fds**              <br> *gauge*     | Number of open file descriptors.                       | every call          |                                  |
| **process_max_fds**               <br> *gauge*     | Maximum number of open file descriptors.               | every call          |                                  |

### 3. Last oracle invocation frame state

The previous and the current frame variables.

| name                                           | description                                          | frequency                                                            | goal                                                                         |
|------------------------------------------------|------------------------------------------------------|----------------------------------------------------------------------|------------------------------------------------------------------------------|
| **deltaSeconds**                  <br> *gauge* | current.timestamp - previous.timestamp               | every SLEEP seconds                                                  | should be approximately equal to the delay between reports                   |
| **appearedValidators**            <br> *gauge* | current.beaconValidators - previous.beaconValidators | every SLEEP seconds                                                  |                                                                              |
| **currentEthV1BlockNumber**       <br> *gauge* | block number of the most current oracle stats check  | every SLEEP seconds                                                  | should be constantly updated and be aligned with https://etherscan.io/blocks |
| **currentValidatorsKeysNumber**   <br> *gauge* | len(validators_keys)                                 | every time there is an unreported frame (1/day or potentially rarer) |                                                                              |
| **currentEpoch**                  <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentTimestamp**              <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentBeaconValidators**       <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentBeaconBalance**          <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentBufferedBalance**        <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentDepositedValidators**    <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentActiveValidatorBalance** <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentTotalPooledEther**       <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentTransientValidators**    <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **currentTransientBalance**       <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevEthV1BlockNumber**          <br> *gauge* | block number of the previous oracle stats check      | every SLEEP seconds                                                  | should be constantly updated and be aligned with https://etherscan.io/blocks |
| **prevEpoch**                     <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevTimestamp**                 <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevBeaconValidators**          <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevBeaconBalance**             <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevBufferedBalance**           <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevDepositedValidators**       <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevActiveValidatorBalance**    <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevTotalPooledEther**          <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevTransientValidators**       <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |
| **prevTransientBalance**          <br> *gauge* |                                                      | every SLEEP seconds                                                  |                                                                              |

### 4. stETH Oracle state

Current stETH price in the pool and the price oracle.

| name                                           | description | frequency  | goal |
|------------------------------------------------|-------------|------------|------|
| **stethOraclePrice**              <br> *gauge* |             | every call |      |
| **stethPoolPrice**                <br> *gauge* |             | every call |      |

### 5. Exceptions

Exception counters.

| name                                           | description                                              |
|------------------------------------------------|----------------------------------------------------------|
| **underpricedExceptionsCount**    <br> *gauge* | count of ValueError: replacement transaction underpriced |
| **transactionTimeoutCount**       <br> *gauge* | count of web3.exceptions.TimeExhausted                   |
| **beaconNodeTimeoutCount**        <br> *gauge* | count of beacon node connection timeouts                 |
| **exceptionsCount**               <br> *gauge* | count of all other exceptions                            |

### Alert examples

Metrics provided allow for multiple useful alerts on oracle health and performance.
We strongly recommend setting up at least two alerts as follows:
- There were no Beacon oracle reports about the last finalized Beacon epoch for more than 30 minutes since that epoch has become finalized.
```
  - alert: reported_frame
    expr: currentEpoch > prevEpoch 
    for: 30m
    labels:
      severity: critical
    annotations:
      title: No report for current frame for 30 minutes
```
- Curve stETH pool live price (`stethPoolPrice` gauge) differs from the stETH oracle's price (`stethOraclePrice` gauge) by more than 5% for at least 10 minutes. 
```
  - alert: peg
    expr: abs((stethPoolPrice - stethOraclePrice)/stethOraclePrice)  > 0.05
    for: 10m
    labels:
      severity: critical
    annotations:
      title: Peg difference is greater than 5%
      description: Peg difference is greater than 5% for more than 10 minutes.
```

# License

2020 Lido <info@lido.fi>

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