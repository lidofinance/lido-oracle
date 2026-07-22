import logging
from typing import cast

from eth_account.signers.local import LocalAccount
from eth_typing import ChecksumAddress
from web3 import Web3
from web3.contract.contract import ContractFunction
from web3.module import Module

from src.providers.execution.contracts.delegation_contract import DelegationContract


logger = logging.getLogger(__name__)


class SignerModule(Module):
    """Resolves which configured account is the oracle's current active on-chain identity.

    Up to two accounts can be configured (`account_1`, `account_2`) to support key rotation
    without downtime. There is only ever one delegation contract. On every cycle,
    `process_members` is given the current HashConsensus member list and decides:

    - if the delegation contract's address is a member, the active signer is whichever
      configured account is currently its delegate (see DelegationContract.assignDelegate);
    - otherwise, the active signer is whichever configured account is a member directly (a
      plain EOA member, no delegation involved).

    `active_signer` is re-resolved from scratch on every call - nothing is carried over from
    a previous cycle - so a rotation enacted on-chain takes effect on the next cycle with no
    restart needed.
    """

    active_signer: LocalAccount | None
    is_delegated: bool
    delegation_contract: DelegationContract | None

    def __init__(
        self,
        w3: Web3,
        account_1: LocalAccount | None,
        account_2: LocalAccount | None,
        delegation_contract_address: str | None,
    ):
        super().__init__(w3)
        self.account_1 = account_1
        self.account_2 = account_2

        self.active_signer = None
        self.is_delegated = False
        self.delegation_contract = None

        if delegation_contract_address:
            logger.info({'msg': 'Initialize delegation contract.', 'address': delegation_contract_address})
            self.delegation_contract = cast(
                DelegationContract,
                self.w3.eth.contract(
                    address=Web3.to_checksum_address(delegation_contract_address),
                    ContractFactoryClass=DelegationContract,
                    decode_tuples=True,
                ),
            )

    def process_members(self, members: list[ChecksumAddress]) -> None:
        """Resolve the active signer from the current HashConsensus member list.

        Resets `active_signer`/`is_delegated` before resolving, so a member/delegatee that is no
        longer valid never lingers from a previous cycle.
        """
        self.active_signer = None
        self.is_delegated = False

        if self.delegation_contract is not None and self.delegation_contract.address in members:
            current_delegate = self.delegation_contract.get_delegate()
            if self._activate_account_matching(current_delegate):
                self.is_delegated = True
            else:
                logger.warning(
                    {
                        'msg': 'Delegation contract is a member, but its current delegate matches none of '
                        'the configured accounts.',
                        'delegation_contract': self.delegation_contract.address,
                        'current_delegate': current_delegate,
                    }
                )
            return

        for address in members:
            if self._activate_account_matching(address):
                return

        logger.warning({'msg': 'None of the configured accounts is an active member.'})

    def _activate_account_matching(self, address: ChecksumAddress) -> bool:
        """Set `active_signer` to whichever configured account matches `address`, if any."""
        if self.account_1 and address == self.account_1.address:
            self.active_signer = self.account_1
            return True

        if self.account_2 and address == self.account_2.address:
            self.active_signer = self.account_2
            return True

        return False

    def wrap_call_for_delegation(self, target_contract_call: ContractFunction) -> ContractFunction:
        """Convert a normal contract call to delegated execution via the delegation contract.

        Args:
            target_contract_call: Original contract function call

        Returns:
            ContractFunction that calls delegation.execute() with encoded data
        """
        if self.delegation_contract is None:
            raise RuntimeError("Delegation is not enabled - no delegation contract configured")

        target_address = Web3.to_checksum_address(target_contract_call.address)
        contract = self.w3.eth.contract(address=target_contract_call.address, abi=target_contract_call.contract_abi)
        encoded = contract.encode_abi(target_contract_call.fn_name, target_contract_call.args)
        calldata = bytes.fromhex(encoded[2:])

        logger.debug(
            {'msg': 'Wrapping call for delegation', 'target': target_address, 'calldata_length': len(calldata)}
        )

        return self.delegation_contract.execute(target_address, calldata)
