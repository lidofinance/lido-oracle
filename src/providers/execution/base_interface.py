import json
import logging
from typing import Any, Self, Type

from web3 import Web3
from web3.types import BlockIdentifier

from src.web3py.contract_tweak import Contract

logger = logging.getLogger(__name__)


class ContractInterface(Contract):
    abi_path: str

    @staticmethod
    def load_abi(abi_file: str) -> dict:
        with open(abi_file) as abi_json:
            return json.load(abi_json)

    @classmethod
    def factory(cls, w3: Web3, class_name: str | None = None, **kwargs: Any) -> Type[Self]:
        if cls.abi_path is None:
            raise AttributeError(f'abi_path attribute is missing in {cls.__name__} class')

        kwargs['abi'] = cls.load_abi(cls.abi_path)
        return super().factory(w3, class_name, **kwargs)

    def is_deployed(self, block: BlockIdentifier) -> bool:
        result = self.w3.eth.get_code(self.address, block_identifier=block) != b""
        logger.info({"msg": f"Check that the contract {self.__class__.__name__} exists at {block=}", "value": result})
        return result
