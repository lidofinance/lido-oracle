from web3.contract.contract import ContractFunction

from providers.execution.base_interface import ContractInterface


class DataBusContract(ContractInterface):
    abi_path = './assets/DataBus.json'

    def send_message(self, event_id: bytes, data: bytes) -> ContractFunction:
        return self.functions.sendMessage(event_id, data)
