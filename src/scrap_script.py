import binascii
import os

import requests
import sys
from eth_abi import decode

from src.main import run_oracle

ETHERSCAN_API_KEY = "9NF7PAGYH2AM8XHSXM96S1TJ7ZKVPP59YB"


# 🔹 Fetch the last 20 transactions of a contract
def get_transactions(contract_address, selector):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={contract_address}&sort=desc&apikey={ETHERSCAN_API_KEY}"

    response = requests.get(url)
    data = response.json()

    if data["status"] != "1":
        print("Error fetching transactions:", data["message"])
        return []

    transactions = data["result"]

    # 🔹 Filter only successful transactions
    successful_transactions = [tx for tx in transactions if tx.get("txreceipt_status") == "1"]

    submit_report_calls = [tx for tx in successful_transactions if tx["input"].startswith(selector)][:30]

    return submit_report_calls


def extract_ref_slot(tx_data, type):
    # Remove function selector (first 10 characters "0x12345678")
    raw_data = tx_data[10:]

    raw_bytes = binascii.unhexlify(raw_data)

    f = []
    if type == 'accounting':
        f = [
            "(uint256,uint256,uint256,uint256,uint256[],uint256[],uint256,uint256,uint256,uint256[],uint256,bool,uint256,bytes32,uint256)",
            "uint256"]
    elif type == 'ejector':
        f = ["(uint256,uint256,uint256,uint256,bytes)", "uint256"]
    else:
        f = ["(uint256,uint256,bytes32,string,string,uint256)", "uint256"]
    return decode(f, raw_bytes)


if __name__ == "__main__":
    print(f"---AccountingOracle---")
    accounting_address = "0x852deD011285fe67063a08005c71a85690503Cee"

    transactions = get_transactions(accounting_address, "0xfc7377cd")

    if not transactions:
        print("No submitReportData transactions found!")
        sys.exit(0)

    print(f"✅ Found {len(transactions)} submitReportData calls")

    for tx in transactions:
        tx_hash = tx["hash"]
        decoded_static_values = extract_ref_slot(tx["input"], 'accounting')
        refslot = decoded_static_values[0][1]
        print(f"🔹 Tx: {tx_hash} → X: {refslot}")
        os.environ["ORACLE_REFSLOT"] = str(refslot)
        os.environ["DEAMON"] = str(False)
        print(decoded_static_values)
        run_oracle('accounting')

    #print(f"---ValidatorExitBusOracle---")
    #ejector_address = "0x0De4Ea0184c2ad0BacA7183356Aea5B8d5Bf5c6e"
    #transactions = get_transactions(ejector_address, "0x294492c8")
    #if not transactions:
    #    print("No submitReportData transactions found!")
    #    sys.exit(0)

    #print(f"✅ Found {len(transactions)} submitReportData calls")
    #for tx in transactions:
    #    tx_hash = tx["hash"]
    #    decoded_static_values = extract_ref_slot(tx["input"], 'ejector')
    #    refslot = decoded_static_values[0][1]
    #    print(f"🔹 Tx: {tx_hash} → X: {refslot}")
    #    os.environ["ORACLE_REFSLOT"] = str(refslot)
    #    os.environ["DEAMON"] = str(False)
    #    print(decoded_static_values)
    #    run_oracle('ejector')

    #print(f"---CSFeeOracle---")
    #csm_oracle_address = "0x4D4074628678Bd302921c20573EEa1ed38DdF7FB"
    #transactions = get_transactions(csm_oracle_address, "0xade4e312")
    #if not transactions:
    #    print("No submitReportData transactions found!")
    #    sys.exit(0)

    #print(f"✅ Found {len(transactions)} submitReportData calls")
    #tx = transactions[0]
    #tx_hash = tx["hash"]
    #decoded_static_values = extract_ref_slot(tx["input"], 'csm')
    #refslot = decoded_static_values[0][1]
    #print(f"🔹 Tx: {tx_hash} → X: {refslot}")
    #os.environ["ORACLE_REFSLOT"] = str(refslot)
    #os.environ["DEAMON"] = str(False)
    #print(decoded_static_values)
    #run_oracle('csm')
