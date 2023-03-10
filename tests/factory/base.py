from pydantic import BaseModel

from tests.factory.web3_factory import Web3Factory
from typings import BlockStamp


class BlockStampModel(BaseModel):
    dataclass: BlockStamp


class BlockStampFactory(Web3Factory):
    __model__ = BlockStampModel


if __name__ == '__main__':
    BlockStampFactory.build()

    o = 1
