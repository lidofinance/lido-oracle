import binascii
import os

import requests
import sys
from eth_abi import decode

from src.main import run_oracle

ETHERSCAN_API_KEY = "<>"

SUBMIT_REPORT_DATA_SELECTOR = "0xfc7377cd"


# 🔹 Fetch the last 20 transactions of a contract
def get_transactions(contract_address):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={contract_address}&sort=desc&apikey={ETHERSCAN_API_KEY}"

    response = requests.get(url)
    data = response.json()

    if data["status"] != "1":
        print("Error fetching transactions:", data["message"])
        return []

    transactions = data["result"]

    # 🔹 Filter only successful transactions
    successful_transactions = [tx for tx in transactions if tx.get("txreceipt_status") == "1"]

    submit_report_calls = [tx for tx in successful_transactions if tx["input"].startswith(SUBMIT_REPORT_DATA_SELECTOR)][:20]

    return submit_report_calls


def extract_ref_slot(tx_data):
    # Remove function selector (first 10 characters "0x12345678")
    raw_data = tx_data[10:]

    raw_bytes = binascii.unhexlify(raw_data)

    format = [
        "(uint256,uint256,uint256,uint256,uint256[],uint256[],uint256,uint256,uint256,uint256[],uint256,bool,uint256,bytes32,uint256)",
        "uint256"]

    decoded_static_values = decode(format, raw_bytes)

    ref_slot = decoded_static_values[0][1]
    return ref_slot


if __name__ == "__main__":
    contract_address = "0x852deD011285fe67063a08005c71a85690503Cee"

    transactions = get_transactions(contract_address)

    if not transactions:
        print("No submitReportData transactions found!")
        sys.exit(0)

    print(f"✅ Found {len(transactions)} submitReportData calls")

    for tx in transactions:
        tx_hash = tx["hash"]
        refslot = extract_ref_slot(tx["input"])
        print(f"🔹 Tx: {tx_hash} → X: {refslot}")
        os.environ["ORACLE_REFSLOT"] = str(refslot)
        os.environ["DEAMON"] = str(False)
        run_oracle('accounting')
