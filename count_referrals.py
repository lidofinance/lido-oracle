#!/usr/bin/env python3
from sqlalchemy import create_engine, Column, Integer, String, Float, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import os
import sys
from web3 import Web3
import json

Base = declarative_base()
SCAN_STEP = 100
ZERO_ADDRESS = "0x"+"0"*40


class DepositCalculator:
    class Deposit(Base):
        __tablename__ = 'deposits'
        id = Column(Integer, primary_key=True)
        addr = Column(String(42))
        amount = Column(Float)
        referral = Column(String(42))

    def __init__(self):
        engine = create_engine('sqlite:///:memory:', echo=False)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.session = Session()

    def get_depo_amounts_grouped_by_referral(self):
        result = self.session.query(
                self.Deposit.referral,
                func.sum(self.Deposit.amount).label("sum"))\
            .filter(self.Deposit.referral != None)\
            .group_by(self.Deposit.referral)\
            .order_by(desc("sum"))\
            .all()
        return(result)

    def get_total_referral_deposits_sum(self):
        result = self.session.query(func.sum(self.Deposit.amount))\
            .filter(self.Deposit.referral != None)\
            .scalar()
        return(result)

    def add_deposit(self, addr=None, amount=None, referral=None):
        if referral == ZERO_ADDRESS:
            referral = None
        deposit = self.Deposit(addr=addr, amount=amount, referral=referral)
        self.session.add(deposit)

    def print_stats(self):
        depo_amounts = self.get_depo_amounts_grouped_by_referral()
        depo_total_sum = self.get_total_referral_deposits_sum()
        print('\n\nResult:')
        if len(depo_amounts) > 0 and depo_total_sum > 0.0:
            print('referral address                              amount       percentage')
            for depo in depo_amounts:
                percentage = depo[1]*100/depo_total_sum
                print(f'{depo[0]:42} {depo[1]:9.4f} eth  {percentage:9.4f}%')
            print(f'                                    total: {depo_total_sum:9.4f} eth')
        else:
            print('No deposits')


def main(argv=None, env=[]):
    if argv is None:
        argv = sys.argv

    if env == []:
        env = os.environ

    envs = ['ETH1_NODE', 'DEPOOL_CONTRACT', 'DEPOOL_ABI_FILE']

    for env in envs:
        if env not in os.environ:
            print(env, 'is missing')
            exit(1)

    try:
        START_BLOCK = int(argv[1])
    except IndexError:
        START_BLOCK = 0
    try:
        END_BLOCK = int(argv[2])
    except IndexError:
        END_BLOCK = None

    depool_abi_path = os.environ['DEPOOL_ABI_FILE']
    eth1_provider = os.environ['ETH1_NODE']
    depool_address = os.environ['DEPOOL_CONTRACT']

    print(f"""
    START_BLOCK = {START_BLOCK} (from command line)
    END_BLOCK = {END_BLOCK} (from command line)
    ETH1_NODE = {eth1_provider}
    DEPOOL_ABI = {depool_abi_path}
    DEPOOL_ADDR = {depool_address}
    """)
    w3 = Web3(Web3.HTTPProvider(eth1_provider))
    with open(depool_abi_path, 'r') as abi:
        depool_abi = json.loads(abi.read())['abi']
    depool_contract = w3.eth.contract(
        address=depool_address,
        abi=depool_abi
    )
    if not END_BLOCK:
        END_BLOCK = w3.eth.getBlock('latest')['number']
    calc = DepositCalculator()
    from_block = START_BLOCK
    total_events = 0
    while True:
        to_block = from_block + SCAN_STEP - 1
        if to_block > END_BLOCK:
            to_block = END_BLOCK
        print(f'Scanning blocks {from_block} to {to_block}', end='')
        events = depool_contract.events.Submitted.getLogs(
            fromBlock=from_block, toBlock=to_block)
        if len(events) > 0:
            for event in events:
                calc.add_deposit(
                    addr=event.args.sender,
                    amount=event.args.amount/1e18,
                    referral=event.args.referral)
            total_events += len(events)
            print(f' found:{len(events)} total:{total_events}')
        else:
            print('')
        from_block = to_block + 1
        if from_block > END_BLOCK:
            break
    calc.print_stats()


if __name__ == "__main__":
    sys.exit(main())
