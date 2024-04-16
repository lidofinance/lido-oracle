import json
from typing import Optional, Any

from web3 import Web3
from web3.contract import Contract


class ContractInterface(Contract):
    abi_path: str = None

    @staticmethod
    def load_abi(abi_file: str) -> dict:
        with open(abi_file) as abi_json:
            return json.load(abi_json)

    @classmethod
    def factory(cls, web3: Web3, class_name: Optional[str] = None, **kwargs: Any) -> 'Contract':
        if cls.abi_path is None:
            raise AttributeError(f'abi_path attribute is missing in {cls.__name__} class')

        kwargs['abi'] = cls.load_abi(cls.abi_path)
        return super().factory(web3, class_name, **kwargs)
