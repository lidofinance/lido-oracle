# DePool Py-Oracle

Pythonic oracle daemon for DePool decentralized staking service. Periodically reports Ethereum 2.0 beacon chain states (validators' balances and statuses) to the DePool dApp contract running on Ethereum 1.0 ledger.

## How it works

* After the start Oracle connects to both nodes: Ethereum 1.0 and Ethereum 2.0 beaconchain.

* Upon the start and then periodically Oracle polls DePool contract, gets the last known epoch and validators to watch for.

* Oracle periodically scans Beacon node 2.0 for epoch number. Every 7200th epoch it reports the stats for each known validator to the DePool contract.

## Run

define the environment variables

```
export ETH1_NODE='http://127.0.0.1:8139'
export ETH2_NODE='http://127.0.0.1:8140'
export DEPOOL_CONTRACT='0xdeadbeef'
export REPORT_INTVL_EPOCHS=7200 
python3 oracle.py
```

## Test

WIP