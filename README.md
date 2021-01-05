# Lido-Oracle daemon

[![Tests](https://github.com/lidofinance/lido-oracle/workflows/Tests/badge.svg?branch=daemon_v2)](https://github.com/lidofinance/lido-oracle/actions)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Oracle daemon for [Lido](https://lido.fi) decentralized staking service. Collects and reports Ethereum 2.0 beacon chain states (the number of visible validators and their summarized balances) to the Lido dApp contract running on Ethereum 1.0 side.

## How it works

* Upon the start daemon determines the reportable epoch and retrieves the list of validator keys to watch for.

* Then it Gets the Lido-controlled validators from the reportable beacon state and summarizes their balances.

* Constructs the transaction containing the `epochId`, `beaconBalance`, and `beaconValidators`.

* If the daemon has `MEMBER_PRIV_KEY` in its environment (i.e. isn't running in dry-run mode), it signs and sends the transaction to the oracle contract (asking for user confirmation if running interactively).

* If the oracle runs in the daemon mode (with `DAEMON=1` env ) it waits `SLEEP` seconds and restarts the loop.

## Setup

The oracle daemon requires fully-syncedd ETH1.0 and Beacon nodes. We highly recommend using
[geth](https://geth.ethereum.org/docs/install-and-build/installing-geth#run-inside-docker-container) and
[Lighthouse](https://lighthouse-book.sigmaprime.io/docker.html#using-the-docker-image).

Note: Prysm beacon client is also supported, but has less API performance.

```sh
docker run -d --name geth -v $HOME/.geth:/root -p 30303:30303 -p 8545:8545 ethereum/client-go --http --http.addr=0.0.0.0
docker run -d --name lighthouse -v $HOME/.ligthouse:/root/.lighthouse  -p 9000:9000 -p 5052:5052 sigp/lighthouse lighthouse beacon --http --http-address 0.0.0.0
```

## Run

The oracle receives its configuration via ENVironment variables. You need to provide URIs of both nodes and the Lido contract address. The following snippet (adapted to your setup) will start the oracle in safe, read-only mode called **Dry-run**. It will run the single loop iteration, calculate the report and print it out instead of sending real TX.

```sh
export ETH1_NODE=http://localhost:8545
export BEACON_NODE=http://lighthouse:5052
export POOL_CONTRACT=0x12aa6ec7d603dc79eD663792E40a520B54A7ae6A
export DAEMON=0
export ORACLE_FROM_BLOCK=11595281
docker run -e ETH1_NODE -e BEACON_NODE -e POOL_CONTRACT -e DAEMON -it lidofinance/oracle:0.1.2
```

Other pre-built oracle images can be found in the [Lido dockerhub](https://hub.docker.com/r/lidofinance/oracle/tags?page=1&ordering=last_updated).

See **Other examples** below for transactable modes.

## Full list of configuration options

* `ETH1_NODE` - HTTP or WS URL of web3 Ethereum node (tested with Geth). **Required**.
* `BEACON_NODE` - HTTP endpoint of Beacon Node (Lighthouse recommended, also tested with Prysm). **Required**.
* `POOL_CONTRACT` - Lido contract in EIP-55 (mixed-case) hex format. **Required**. Example: `0x12aa6ec7d603dc79eD663792E40a520B54A7ae6A`
* `DAEMON` - with `DAEMON=0` runs the single iteration then quits. `DAEMON=0` in combination with `MEMBER_PRIV_KEY` runs interactively and asks user for confirmation before sending each TX. With `DAEMON=1` runs autonomously (without confirmation) in an indefinite loop. **Optional**. Default: `0`
* `MEMBER_PRIV_KEY` - Hex-encoded private key of Oracle Quorum Member address. **Optional**. If omitted, the oracle runs in read-only (dry-run) mode. WARNING: Keep `MEMBER_PRIV_KEY` safe. Since it keeps real Ether to pay gas, it should never be exposed outside.
* `FORCE` - The oracle makes the sanity checks on the collected data before reporting. Running in `DAEMON` mode, if data look suspicious, it skips sending TX. In enforced mode it gets reported even if it looks suspicious. It's unsafe and used for smoke testing purposes, NEVER use it in production!  **Optional**. Default: `0`
* `SLEEP` seconds - The interval between iterations in Daemon mode. Default value: 60 s. Effective with `DAEMON=1` only.
* `GAS_LIMIT` - The pre-defined gasLimit for composed transaction. Defaulf value: 1 500 000. Effective in transactable mode (with given `MEMBER_PRIV_KEY`)
* `ORACLE_FROM_BLOCK` - The earlist block to check for oracle events. Needed on mainnet first run to skip 5 minutes of scanning blockchain for events that are not there, recommended to be set to 11595281 on mainnet deployments

## Other examples

* WARNING: The examples below are **transactable** and can potentially break the Lido. You must understand the protocol and what you are doing.
* WARNING: Keep your `MEMBER_PRIV_KEY` safe. Since it keeps real Ether to pay gas, it should never be exposed outside.
* WARNING: Never use the `MEMBER_PRIV_KEY` value given below. You will definitely lose all your Ethers if reuse that private key.

### Interactive supervised mode

This mode is intended for controlled start and allows to double-check the report and its effects before its actual sending. Runs the single iteration and asks for confirmation via interactive `[y/n]` prompt before sending real TX to the network. You should be connected (attached) to the terminal to see this.

```sh
export ETH1_NODE=http://localhost:8545
export BEACON_NODE=http://lighthouse:5052
export POOL_CONTRACT=0x12aa6ec7d603dc79eD663792E40a520B54A7ae6A
export MEMBER_PRIV_KEY=0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
export DAEMON=0
export ORACLE_FROM_BLOCK=11595281
docker run -e ETH1_NODE -e BEACON_NODE -e POOL_CONTRACT -e DAEMON -e MEMBER_PRIV_KEY -it lidofinance/oracle:0.1.2
```

### Autonomous mode

Runs in the background with 1-hour pauses between consecutive iterations. To be used without human supervision (on later stages).

```sh
export ETH1_NODE=http://localhost:8545
export BEACON_NODE=http://lighthouse:5052
export POOL_CONTRACT=0x12aa6ec7d603dc79eD663792E40a520B54A7ae6A
export MEMBER_PRIV_KEY=0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
export DAEMON=1
export SLEEP=3600
export ORACLE_FROM_BLOCK=11595281
docker run -e ETH1_NODE -e BEACON_NODE -e POOL_CONTRACT -e DAEMON -e MEMBER_PRIV_KEY -e SLEEP lidofinance/oracle:0.1.2
```

## Build yourself

Instead of downloading the image from dockerhub, you can build it yourself. This requires git and python3.8+.

```sh
./build.sh [--push]
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
