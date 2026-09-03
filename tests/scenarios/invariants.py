"""Correctness invariants for oracle report scenarios.

These functions encode properties that a *correct* report must satisfy regardless of the
scenario that produced it. They are the framework's correctness floor (see
``docs/oracle-testing-framework-plan.md`` §5.3): scenarios may be added or removed freely, but
every generated report is checked against the relevant invariants here.

Invariants are written to verify the report against the *on-chain contract's* expectations
(byte layout, count consistency, ordering), independently of how the oracle's own encoder is
implemented — so a regression in the encoder is caught rather than masked.
"""

from typing import NamedTuple


# Exit Bus (VEBO) DATA_FORMAT_LIST_WITH_KEY_INDEX packed-entry layout.
# Mirrors the contract-side layout, kept here as the independently-verified spec:
#   MSB <----------------------------------------------------------------- LSB
#   | 3 bytes  | 5 bytes  |     8 bytes     |  8 bytes  |    48 bytes     |
#   | moduleId | nodeOpId | validatorIndex  | keyIndex  | validatorPubkey |
DATA_FORMAT_LIST_WITH_KEY_INDEX = 2

_MODULE_ID_LEN = 3
_NODE_OP_ID_LEN = 5
_VALIDATOR_INDEX_LEN = 8
_KEY_INDEX_LEN = 8
_PUBKEY_LEN = 48
_ENTRY_LEN = _MODULE_ID_LEN + _NODE_OP_ID_LEN + _VALIDATOR_INDEX_LEN + _KEY_INDEX_LEN + _PUBKEY_LEN  # 72


class ExitRequest(NamedTuple):
    module_id: int
    node_op_id: int
    validator_index: int
    key_index: int
    pubkey: bytes


def decode_ejector_data(data: bytes) -> list[ExitRequest]:
    """Decode a VEBO ``DATA_FORMAT_LIST_WITH_KEY_INDEX`` payload into its exit requests."""
    if len(data) % _ENTRY_LEN != 0:
        raise ValueError(f"ejector data length {len(data)} is not a multiple of entry size {_ENTRY_LEN}")

    requests: list[ExitRequest] = []
    for offset in range(0, len(data), _ENTRY_LEN):
        entry = data[offset : offset + _ENTRY_LEN]
        cursor = 0
        module_id = int.from_bytes(entry[cursor : (cursor := cursor + _MODULE_ID_LEN)])
        node_op_id = int.from_bytes(entry[cursor : (cursor := cursor + _NODE_OP_ID_LEN)])
        validator_index = int.from_bytes(entry[cursor : (cursor := cursor + _VALIDATOR_INDEX_LEN)])
        key_index = int.from_bytes(entry[cursor : (cursor := cursor + _KEY_INDEX_LEN)])
        pubkey = entry[cursor : cursor + _PUBKEY_LEN]
        requests.append(ExitRequest(module_id, node_op_id, validator_index, key_index, pubkey))
    return requests


def check_ejector_report_wellformed(report: tuple) -> None:
    """Assert an ejector ``ReportData`` tuple is internally consistent and correctly ordered.

    Report tuple order (``src/modules/oracles/ejector/types.py``):
    ``(consensus_version, ref_slot, requests_count, data_format, data)``.

    Checks:
      * the payload uses the only valid VEBO list format;
      * ``requests_count`` matches the number of entries actually packed into ``data``
        (a mismatch reverts on-chain);
      * every entry is a full 72-byte record;
      * requests are strictly ordered by ``(module_id, node_op_id, validator_index)`` — the
        VEBO contract requires ascending, duplicate-free order.
    """
    assert len(report) == 5, f"ejector report must have 5 fields, got {len(report)}"
    _consensus_version, _ref_slot, requests_count, data_format, data = report

    assert data_format == DATA_FORMAT_LIST_WITH_KEY_INDEX, f"unexpected data_format {data_format}"
    assert isinstance(data, (bytes, bytearray)), f"data must be bytes, got {type(data)}"

    requests = decode_ejector_data(bytes(data))

    assert len(requests) == requests_count, f"requests_count {requests_count} != decoded entries {len(requests)}"
    if requests_count == 0:
        assert data == b"", "empty report must carry empty data"

    keys = [(r.module_id, r.node_op_id, r.validator_index) for r in requests]
    assert keys == sorted(keys), "exit requests must be sorted by (module_id, node_op_id, validator_index)"
    assert len(set(keys)) == len(keys), "exit requests must not contain duplicate validators"


def check_accounting_module_balance_equality(total_cl_balance_gwei: int, module_balances_gwei: list[int]) -> None:
    """Assert the per-module balance breakdown sums exactly to the total CL balance.

    ``OracleReportSanityChecker`` enforces **strict** equality on-chain between
    ``cl_validators_balance_gwei`` and the sum of ``validator_balances_gwei_by_staking_module``; any
    mismatch reverts the report. This is the invariant the Gloas fallback correction must preserve —
    the in-flight withdrawal add-back has to hit both the total and the per-module breakdown, or
    every fallback-case report with in-flight withdrawals reverts.
    """
    module_sum = sum(module_balances_gwei)
    assert module_sum == total_cl_balance_gwei, (
        f"per-module balance sum {module_sum} != total CL balance {total_cl_balance_gwei}"
    )


def check_accounting_report_wellformed(report: tuple) -> None:
    """Assert an accounting ``ReportData`` tuple is internally consistent.

    The checks mirror structural assumptions made by ``AccountingOracle`` and
    ``OracleReportSanityChecker`` without reusing the oracle's report builder.
    """
    assert len(report) == 19, f"accounting report must have 19 fields, got {len(report)}"
    (
        _consensus_version,
        _ref_slot,
        cl_validators_balance_gwei,
        _cl_pending_balance_gwei,
        exited_module_ids,
        exited_validator_counts,
        balance_module_ids,
        module_balances_gwei,
        _withdrawal_vault_balance,
        _el_rewards_vault_balance,
        _shares_requested_to_burn,
        _withdrawal_finalization_batches,
        _finalization_share_rate,
        _is_bunker,
        _vaults_tree_root,
        _vaults_tree_cid,
        extra_data_format,
        extra_data_hash,
        extra_data_items_count,
    ) = report

    assert len(exited_module_ids) == len(exited_validator_counts), (
        "exited-validator module ids and counts must have equal lengths"
    )
    assert len(balance_module_ids) == len(module_balances_gwei), (
        "balance module ids and balances must have equal lengths"
    )
    assert exited_module_ids == sorted(exited_module_ids), "exited-validator module ids must be sorted"
    assert balance_module_ids == sorted(balance_module_ids), "balance module ids must be sorted"
    assert len(set(exited_module_ids)) == len(exited_module_ids), "exited-validator module ids must be unique"
    assert len(set(balance_module_ids)) == len(balance_module_ids), "balance module ids must be unique"

    check_accounting_module_balance_equality(cl_validators_balance_gwei, module_balances_gwei)

    assert extra_data_format in (0, 1), f"unexpected extra_data_format {extra_data_format}"
    assert isinstance(extra_data_hash, bytes), f"extra_data_hash must be bytes, got {type(extra_data_hash)}"
    assert len(extra_data_hash) == 32, f"extra_data_hash must be 32 bytes, got {len(extra_data_hash)}"
    if extra_data_format == 0:
        assert extra_data_items_count == 0, "empty extra data must have zero items"
