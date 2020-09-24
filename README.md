# DePool Py-Oracle

Pythonic oracle daemon for DePool decentralized staking service. Periodically reports Ethereum 2.0 beacon chain states (validators' balances and statuses) to the DePool dApp contract running on Ethereum 1.0 ledger.

## How it works

* After the start Oracle connects to both nodes: Ethereum 1.0 and Ethereum 2.0 beaconchain.

* Upon the start and then periodically Oracle polls DePool contract, gets the last known epoch and validators to watch for.

* Oracle periodically scans Beacon node 2.0 for epoch number. Every 7200th epoch it reports the stats for each known validator to the DePool contract.

## Run

define the environment variables

```sh
export ETH1_NODE='http://127.0.0.1:8545'
export BEACON_NODE='http://127.0.0.1:5052'
export DEPOOL_ABI='dePool.abi'
export ORACLE_ABI='oracle.abi'
export DEPOOL_ADDR='0xfe18BCBeDD6f46e0DfbB3Aea02090F23ED1c4a28'
export ORACLE_ADDR='0x2e25c8F88c5cCcbC9400e5bc86cF9C58C7604327'
export SENDER_PRIV_KEY=0xa8a54b2d8197bc0b19bb8a084031be71835580a01e70a45a13babd16c9bc1563
python3 oracle.py
```

## Test

WIP

## Helpers

### Referral counter

Parses submission events on PoW side and counts referral statistics

```sh
export ETH1_NODE='http://127.0.0.1:8545'
export DEPOOL_ABI='dePool.abi'
export DEPOOL_ADDR='0xfe18BCBeDD6f46e0DfbB3Aea02090F23ED1c4a28'
python3 count_referrals.py <start block> <end block>
```
