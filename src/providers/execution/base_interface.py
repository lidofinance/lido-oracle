import json
from typing import Optional, Any, Self

from web3 import Web3

from src.web3py.contract_tweak import Contract


class ContractInterface(Contract):
    abi_path: str

    @staticmethod
    def load_abi(abi_file: str) -> dict:
        with open(abi_file) as abi_json:
            return json.load(abi_json)

    @classmethod
    def factory(cls, w3: Web3, class_name: Optional[str] = None, **kwargs: Any) -> Self:
        if cls.abi_path is None:
            raise AttributeError(f'abi_path attribute is missing in {cls.__name__} class')

        kwargs['abi'] = cls.load_abi(cls.abi_path)
        return super().factory(w3, class_name, **kwargs)
