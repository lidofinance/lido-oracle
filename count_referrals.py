#!/usr/bin/env python3
from sqlalchemy import create_engine, Column, Integer, String, Float, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

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
