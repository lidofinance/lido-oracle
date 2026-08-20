"""Report-golden scenarios for the ejector module (framework Layer 1).

See ``docs/oracle-testing-framework-plan.md``. These build the *full* ejector ``ReportData``
tuple end-to-end (through ``Ejector.build_report``) from controlled inputs, then assert both an
exact golden tuple and the shared correctness invariants in ``tests/scenarios/invariants.py``.

Layer 1 is fully offline (network blocked, ``@pytest.mark.unit``): the eject list is injected at
the ``get_validators_to_eject`` seam so a scenario maps deterministically to one report. Later
iterations replace the injected list with a recorded CL/EL cassette (Layer 2/3) without changing
the assertions here.
"""

from typing import cast
from unittest.mock import Mock

import pytest

from src.constants import ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.modules.oracles.ejector.ejector import Ejector
from src.providers.consensus.types import Validator
from src.types import ReferenceBlockStamp
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    LidoValidatorsProvider,
    NodeOperatorGlobalIndex,
    NodeOperatorId,
    StakingModuleId,
)
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import (
    LidoKeyFactory,
    LidoValidatorFactory,
    ValidatorFactory,
    ValidatorStateFactory,
)
from tests.scenarios.invariants import DATA_FORMAT_LIST_WITH_KEY_INDEX, check_ejector_report_wellformed


CONSENSUS_VERSION = 3


def _lido_validator(validator_index: int, key_index: int, pubkey_hex: str) -> LidoValidator:
    """Build a LidoValidator with the exact fields the encoder reads, everything else faked."""
    return LidoValidatorFactory.build(
        index=validator_index,
        validator=ValidatorStateFactory.build(pubkey=pubkey_hex),
        lido_id=LidoKeyFactory.build(index=key_index),
    )


def _packed_entry(module_id: int, op_id: int, validator_index: int, key_index: int, pubkey: bytes) -> bytes:
    """Independently packed VEBO entry, used to pin the golden ``data`` bytes."""
    return module_id.to_bytes(3) + op_id.to_bytes(5) + validator_index.to_bytes(8) + key_index.to_bytes(8) + pubkey


@pytest.fixture()
def ref_blockstamp() -> ReferenceBlockStamp:
    return cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build())


@pytest.fixture()
def ejector(web3: Web3) -> Ejector:
    web3.lido_contracts.validators_exit_bus_oracle.get_consensus_version = Mock(return_value=1)
    module = Ejector(web3)
    # Inputs the report body reads but that are not under test in Layer 1.
    module.get_consensus_version = Mock(return_value=CONSENSUS_VERSION)
    module.w3.lido_contracts.get_ejector_last_processing_ref_slot = Mock(return_value=0)
    return module


@pytest.mark.unit
@pytest.mark.scenario
class TestEjectorReportScenarios:
    def test_build_report__no_validators_to_eject__empty_wellformed_report(
        self, ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        # Arrange — EJ-02: predictable EL balance already covers demand, nothing to eject.
        ejector.get_validators_to_eject = Mock(return_value=[])

        # Act
        report = ejector.build_report(ref_blockstamp)

        # Assert
        assert report == (CONSENSUS_VERSION, ref_blockstamp.ref_slot, 0, DATA_FORMAT_LIST_WITH_KEY_INDEX, b"")
        check_ejector_report_wellformed(report)

    def test_build_report__unsorted_validators__sorted_wellformed_golden(
        self, ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        # Arrange — EJ-01 (lite): three validators supplied out of order across two modules.
        pk_a, pk_b, pk_c = "0x" + "aa" * 48, "0x" + "bb" * 48, "0x" + "cc" * 48
        val_a = ((StakingModuleId(2), NodeOperatorId(1)), _lido_validator(50, 7, pk_a))
        val_b = ((StakingModuleId(1), NodeOperatorId(3)), _lido_validator(200, 2, pk_b))
        val_c = ((StakingModuleId(1), NodeOperatorId(3)), _lido_validator(10, 9, pk_c))
        unsorted: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = [val_a, val_b, val_c]
        ejector.get_validators_to_eject = Mock(return_value=unsorted)

        # Expected: sorted by (module_id, node_op_id, validator_index) -> c, b, a.
        expected_data = (
            _packed_entry(1, 3, 10, 9, bytes.fromhex("cc" * 48))
            + _packed_entry(1, 3, 200, 2, bytes.fromhex("bb" * 48))
            + _packed_entry(2, 1, 50, 7, bytes.fromhex("aa" * 48))
        )

        # Act
        report = ejector.build_report(ref_blockstamp)

        # Assert
        assert report == (CONSENSUS_VERSION, ref_blockstamp.ref_slot, 3, DATA_FORMAT_LIST_WITH_KEY_INDEX, expected_data)
        check_ejector_report_wellformed(report)


# EIP-7732 (Gloas) adds a builder registry alongside the validator registry. In fields typed as
# ValidatorIndex, builder entries are distinguished by setting bit 40 (docs/glamsterdam-oracle-changes.md
# §4). The flag is defined here in the test on purpose: the ejector performs NO index masking, so no such
# constant exists in ``src`` — its builder-safety comes from a different mechanism (see the class docstring).
BUILDER_INDEX_FLAG = 2**40
_BUILDER_PUBKEY = "0x" + "bb" * 48
_BUILDER_WITHDRAWAL_PREFIX = "0x03"  # EIP-7732 builder credential; Lido keys use 0x01/0x02 only.


@pytest.mark.unit
@pytest.mark.scenario
class TestEjectorBuilderEntriesExcluded:
    """EJ-09 — builder-registry entries can never enter the ejector's eject list.

    The plan's original framing (mask ``BUILDER_INDEX_FLAG`` before using ``w.validator_index`` as an
    array index) does not apply to the ejector: it performs no such index masking. Instead the eject
    candidate set is built by ``compute_lido_validators`` as a **pubkey-keyed intersection** of the KAPI
    *used Lido keys* with the CL validator registry. A builder entry is absent from the KAPI key set
    (Lido keys use 0x01/0x02 credentials), so it never matches a pubkey, never becomes a
    ``LidoValidator``, and its 2**40-flagged index is therefore never used to index ``state.validators``
    anywhere downstream (``ValidatorExitIterator`` iterates only the resulting Lido validators). The
    guarantee is structural, not defensive.

    This is the Layer-1 coverage for EJ-09; there is no Layer-2 variant because the exclusion is a
    property of the key filter, independent of any on-chain submission path. Priority is correctness:
    the assertions pin the result to an independently derived set, not merely a well-formed shape.
    """

    @staticmethod
    def _lido_cl_validator(index: int, pubkey: str) -> Validator:
        """A genuine Lido validator as seen on the CL: real (small) index, 0x01 credentials."""
        return ValidatorFactory.build(
            index=index,
            validator=ValidatorStateFactory.build(pubkey=pubkey, withdrawal_credentials=ETH1_ADDRESS_WITHDRAWAL_PREFIX),
        )

    @staticmethod
    def _builder_registry_entry() -> Validator:
        """An EIP-7732 builder-registry entry: 2**40-flagged index, 0x03 credentials, non-Lido pubkey."""
        return ValidatorFactory.build(
            index=BUILDER_INDEX_FLAG + 7,
            validator=ValidatorStateFactory.build(
                pubkey=_BUILDER_PUBKEY, withdrawal_credentials=_BUILDER_WITHDRAWAL_PREFIX
            ),
        )

    def test_compute_lido_validators__builder_entry_in_registry__matched_only_by_pubkey(self) -> None:
        # Arrange — three genuine Lido validators (real indices) plus one builder-registry entry carrying
        # a 2**40-flagged index, all sharing the single CL validator list.
        lido_pubkeys = ["0x" + p * 48 for p in ("11", "22", "33")]
        lido_cl = [self._lido_cl_validator(i, pk) for i, pk in zip((1, 2, 3), lido_pubkeys, strict=True)]
        cl_validators = [*lido_cl, self._builder_registry_entry()]
        # KAPI returns used keys ONLY for the genuine Lido validators — builders are never Lido keys.
        used_keys = LidoKeyFactory.generate_for_validators(lido_cl)

        # Act — the exact function ValidatorExitIterator / get_validators_to_eject derive candidates from.
        active, pending = LidoValidatorsProvider.compute_lido_validators(used_keys, cl_validators)

        # Assert — independent ground truth: exactly the three Lido validators, matched by pubkey.
        assert [v.index for v in active] == [1, 2, 3]
        assert {v.validator.pubkey for v in active} == set(lido_pubkeys)
        assert _BUILDER_PUBKEY not in {v.validator.pubkey for v in active}
        # The builder entry appears in neither list; matching is by pubkey, never by position/index.
        assert pending == []
        for v in active:
            assert v.lido_id.key == v.validator.pubkey
        # No builder-flagged index survives into the eject-candidate set.
        assert all(v.index < BUILDER_INDEX_FLAG for v in active)

    def test_get_active_lido_validators__builder_entry_in_cl_state__excluded_via_key_filter(self, web3: Web3) -> None:
        # Arrange — same corpus, exercised through the real provider seam the ejector consumes.
        blockstamp = cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build())
        lido_pubkeys = ["0x" + p * 48 for p in ("44", "55", "66")]
        lido_cl = [self._lido_cl_validator(i, pk) for i, pk in zip((10, 11, 12), lido_pubkeys, strict=True)]
        cl_validators = [*lido_cl, self._builder_registry_entry()]

        web3.cc.get_validators = Mock(return_value=cl_validators)
        web3.kac.get_used_lido_keys = Mock(return_value=LidoKeyFactory.generate_for_validators(lido_cl))
        web3.cc.get_pending_deposits = Mock(return_value=[])
        web3.cc.get_pending_consolidations = Mock(return_value=[])
        web3.cc.get_validators_by_indexes = Mock(return_value={})
        web3.lido_validators._kapi_sanity_check = Mock()

        # Act
        result = web3.lido_validators.get_active_lido_validators(blockstamp)

        # Assert — the builder entry never becomes an ejectable Lido validator; no IndexError is raised.
        assert len(result) == 3
        assert {v.validator.pubkey for v in result} == set(lido_pubkeys)
        assert _BUILDER_PUBKEY not in {v.validator.pubkey for v in result}
        assert all(v.index < BUILDER_INDEX_FLAG for v in result)
