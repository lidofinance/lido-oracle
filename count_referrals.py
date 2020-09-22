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
        result = self.session.query(self.Deposit.referral, func.sum(self.Deposit.amount).label("sum"))\
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
        deposit = self.Deposit(addr=addr, amount=amount, referral=referral)
        self.session.add(deposit)


def main(argv=None, env=[]):
    if argv is None:
        argv = sys.argv
    if env == []:
        env = os.environ
    try:
        START_BLOCK = int(argv[1])
    except IndexError:
        START_BLOCK = 0
    try:
        END_BLOCK = int(argv[2])
    except IndexError:
        END_BLOCK = None
    try:
        ETH1_NODE = env['ETH1_NODE']
    except KeyError:
        print("need to set ETH1_NODE env variable")
        exit()
    try:
        DEPOOL_ABI = env['DEPOOL_ABI']
    except KeyError:
        print("need to set DEPOOL_ABI env variable")
        exit()
    try:
        DEPOOL_ADDR = env['DEPOOL_ADDR']
    except KeyError:
        print("need to set DEPOOL_ADDR env variable")
        exit()
    print(f"""
    START_BLOCK = {START_BLOCK}
    END_BLOCK = {END_BLOCK}
    ETH1_NODE = {ETH1_NODE}
    DEPOOL_ABI = {DEPOOL_ABI}
    DEPOOL_ADDR = {DEPOOL_ADDR}
    """)
    w3 = Web3(Web3.HTTPProvider(ETH1_NODE))
    with open(DEPOOL_ABI, 'r') as abi:
        depool_abi = json.loads(abi.read())['abi']
    depool_contract = w3.eth.contract(
        address=DEPOOL_ADDR,
        abi=depool_abi
    )
    if not END_BLOCK:
        END_BLOCK = w3.eth.getBlock('latest')['number']
    current_block = START_BLOCK
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
            print(from_block, to_block, events)
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


if __name__ == "__main__":
    sys.exit(main())
