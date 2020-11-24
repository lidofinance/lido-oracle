# Lido-Oracle

![Tests](https://github.com/lidofinance/lido-oracle/workflows/Tests/badge.svg)

Pythonic oracle daemon for DePool decentralized staking service. Periodically reports Ethereum 2.0 beacon chain states (validators' balances and statuses) to the DePool dApp contract running on Ethereum 1.0 ledger.

## How it works

* After the start Oracle connects to both nodes: Ethereum 1.0 and Ethereum 2.0 beaconchain.

* Upon the start and then periodically Oracle polls Lido contract, gets the last known epoch and validators to watch for.

* Oracle periodically scans Beacon node 2.0 for epoch number. Every 7200th slot it reports the stats for each known validator to the Lido contract.

## Run

define the environment variables:

```sh
export ETH1_NODE="http://localhost:8545"
export BEACON_NODE="http://localhost:5052"
export POOL_CONTRACT="0x12aa6ec7d603dc79eD663792E40a520B54A7ae6A"
export MEMBER_PRIV_KEY="0xa8a54b2d8197bc0b19bb8a084031be71835580a01e70a45a13babd16c9bc1563"
```

dry run without actually sending a tx:

```sh
python3 oracle.py
```

run as a command line util, push reportBeacon tx once and exit after that:

```sh
python3 oracle.py --submit-tx
```

run as a daemon:

```sh
python3 oracle.py --daemon --submit-tx
```

## Test

To run tests you need all test dependencies installed

```
pip install -U -r requirements-test.txt
```

To run tests just type

```python
pytest
```

## Helpers

### Referral counter

Parses submission events on PoW side and counts referral statistics

```sh
export ETH1_NODE='http://127.0.0.1:8545'
export LIDO_ABI='Lido.abi'
export LIDO_ADDR='0xfe18BCBeDD6f46e0DfbB3Aea02090F23ED1c4a28'
python3 count_referrals.py <start block> <end block>
```

## Work with e2e environment

1. run e2e enviroment lido-dao project(<https://github.com/lidofinance/lido-dao>). Testing on commit c63a05fa6bfa8cdf0360c2741c37a780eee0b093 

2. Define the environment variables.

    Contract addresses may not match. The current addresses will be available in the Aragon web interface(<http://localhost:3000/#/lido-dao/>)

    ```bash
    export ETH1_NODE="http://localhost:8545"
    export BEACON_NODE="http://localhost:5052"
    export POOL_CONTRACT="0x12aa6ec7d603dc79eD663792E40a520B54A7ae6A"
    export MEMBER_PRIV_KEY="0xa8a54b2d8197bc0b19bb8a084031be71835580a01e70a45a13babd16c9bc1563"
    python3 oracle.py
    ```

3. Add permissions to the manager account:
    * SP Registry: Manage signing keys
    * Oracle: Add or remove oracle committee members

4. Make a manager oracle member (Oracle contract function addOracleMember(manager_address))
5. Add validators keys to SP Registry contract (SP Registry contract function addSigningKeys(quantity, pubkeys, signatures)).
    validators pubkeys are available on lido-dao project folder on path  /lido-dao/data/validators

    Keys must be converted. Python example:

    ```python
    import binascii

    pubkey = '810ad9abfc1b1b18e44e52d0dc862d8028c664cbdcadfe301698411386b77b2b1d120c45f688f0d67703286d9dd92910'
    binascii.unhexlify(pubkey)
    ```

6. ```python3 oracle.py```
