#!/usr/bin/env python3
from sqlalchemy import create_engine, Column, Integer, String, Float, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import os
import sys

Base = declarative_base()


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


def main(argv=None, env=[]):
    if argv is None:
        argv = sys.argv
    if env == []:
        env = os.environ
    try:
        START_BLOCK = argv[1]
    except IndexError:
        START_BLOCK = 0
    try:
        END_BLOCK = argv[2]
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


if __name__ == "__main__":
    sys.exit(main())
