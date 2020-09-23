"""
Script for creating deposits. Submits given amount of Ether to the
DePool contract. Used in manual testing procedures.

Usage:
1. define environment variables

export DEPOOL_ABI_FILE='./DePool.abi'
export ETH1_NODE='http://127.0.0.1:8545'
export DEPOOL_CONTRACT='0x53ac5234FEf1762Fd782d2D79F0D65f47489275e'
export MANAGER_PRIV_KEY='deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef'


2. Run the script. The first argument is amount in Ethers (mandatory).
The second - Referral address (optional)

python3 helpers/submit_deposit.py 0.7 0x53ac5234FEf1762Fd782d2D79F0D65f47489275e
OR
python3 helpers/submit_deposit.py 0.2

3. The script will print the transaction hash and receipt
"""

import os
import json
import sys
from eth_keys import keys
from web3 import Web3, WebsocketProvider, HTTPProvider

envs = ['ETH1_NODE', 'DEPOOL_CONTRACT', 'MANAGER_PRIV_KEY', 'DEPOOL_ABI_FILE']

for env in envs:
    if env not in os.environ:
        print(env, 'is missing')
        exit(1)
amount = float(sys.argv[1])
if len(sys.argv) > 2:
    referral = sys.argv[2]
else:
    referral = "0x"+"0"*40

dp_abi_path = os.environ['DEPOOL_ABI_FILE']
eth1_provider = os.environ['ETH1_NODE']
depool_address = os.environ['DEPOOL_CONTRACT']
manager_privkey = os.environ['MANAGER_PRIV_KEY']

print(f"""
DEPOOL_ABI_FILE = {dp_abi_path}
ETH1_NODE = {eth1_provider}
DEPOOL_CONTRACT = {depool_address}
MANAGER_PRIV_KEY = <hidden>
""")

if eth1_provider.startswith('http'):
    w3 = Web3(HTTPProvider(eth1_provider))
elif eth1_provider.starstwith('ws'):
    w3 = Web3(WebsocketProvider(eth1_provider))
else:
    print('Unsupported provider')

with open(dp_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
depool = w3.eth.contract(abi=abi['abi'], address=depool_address)

private_key_bytes = bytes.fromhex(manager_privkey)
pk = keys.PrivateKey(private_key_bytes)
account = pk.public_key.to_checksum_address()
print("ETH address: %s" % account)
balance = float(w3.eth.getBalance(account))/1e18
print("ETH balance: %s" % balance)
assert w3.eth.getBalance(account) > 0, \
    "Not enough balance on address"
assert len(w3.eth.getCode(depool_address)) > 0, \
    "There is no contract by given address"

tx = depool.functions.submit(Web3.toChecksumAddress(referral)).buildTransaction({
    'gasPrice': w3.eth.gasPrice,
    'nonce': w3.eth.getTransactionCount(account, 'latest'),
    'from': account,
    'value': int(amount * 1e18)
})
tx_signed = w3.eth.account.signTransaction(tx, pk)
tx_hash = w3.eth.sendRawTransaction(tx_signed.rawTransaction).hex()
print(f'Transaction {tx_hash} sent')
tx_rcpt = w3.eth.waitForTransactionReceipt(tx_hash)
print(f'Transaction mined. Receipt: {tx_rcpt}')
