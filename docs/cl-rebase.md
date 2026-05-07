# CL Rebase Calculation with Protocol Deposits

## Scope

This document describes how `_calculate_cl_rebase_between_blocks` in `AbnormalClRebase` (bunker mode) should correctly account for capital injected via validator deposits when computing the intraframe CL rebase between `prev_blockstamp` and `ref_blockstamp`.

---

## Problem

Post-EIP-7251, an existing validator with can receive a **top-up deposit** — additional ETH on top of their original stake. The validator pubkey is already present in both `prev_validators` and `ref_validators`, so `calculate_validators_count_diff_in_gwei` ignores it entirely.

The top-up increases `raw_cl_rebase` exactly as if it were earned yield:

```
raw_cl_rebase includes:  +X ETH  (top-up to existing validator)
validators_count_diff:    0       (validator was already in prev — not subtracted)
cl_rebase is inflated:   +X ETH  ← capital injection treated as reward
```

Without correction, bunker mode sees an artificially high rebase and may fail to trigger when it should.

---

## Key Concepts

### Deposit lifecycle

```
  EL Deposit Contract          CL Pending Queue          Active Validator
  ┌──────────────────┐         ┌──────────────┐          ┌─────────────┐
  │  deposit(N ETH)  │──────▶  │   pending    │────────▶ │   active    │
  └──────────────────┘  ~0s    └──────────────┘  epochs  └─────────────┘
                        (EIP-6110)               (churn limited)
```

### Conservation invariant

Let `T1` = `prev_blockstamp`, `T2` = `ref_blockstamp`. Lido ETH deposited strictly within
the window `[T1, T2]` falls into exactly one of two states at `T2`:

```
deposited_in_window = applied_in_window + pending_from_window_at_T2
```

Lido ETH already in the CL queue at `T1` (deposited before the window) satisfies:

```
old_pending_deposits = applied_from_old_queue + still_pending_at_T2
```

Combining both:

```
deposited_in_window + old_pending_deposits
    = (applied_in_window + applied_from_old_queue)
    + (pending_from_window_at_T2 + still_pending_at_T2)
    = total_deposits_injected + current_pending_deposits
```

Rearranging:

```
total_deposits_injected = deposited_in_window + old_pending_deposits - current_pending_deposits
```

This identity holds regardless of queue length or churn rate — no epoch-by-epoch simulation needed.

---

## Algorithm

All values are in **Gwei** (not validator counts) to handle variable deposit amounts post-EIP-7251.

```python
def calculate_injected_capital(
    prev_blockstamp: BlockStamp,
    ref_blockstamp: BlockStamp,
    prev_lido_validators: list[LidoValidator],
    ref_lido_validators: list[LidoValidator],
    lido_keys: list[LidoKey],
) -> Gwei:
    # `depositedForCurrentReport` was introduced in Lido v4 (EIP-7251 upgrade).
    # Check version at the previous oracle report's ref slot (= start of current frame).
    # last_report_blockstamp is obtained via _get_last_report_reference_blockstamp /
    # get_accounting_last_processing_ref_slot — already computed in the calling context.
    last_report_ref_slot = w3.lido_contracts.get_accounting_last_processing_ref_slot(ref_blockstamp)
    if _lido_version_at_block(last_report_ref_slot.block_number) < LIDO_V4:
        prev_pubkeys = {v.validator.pubkey for v in prev_lido_validators}
        new_validators_count = sum(
            1 for v in ref_lido_validators if v.validator.pubkey not in prev_pubkeys
        )
        return Gwei(new_validators_count * 32 * 10**9)

    # Filter pending deposits by pubkey registered in KAPI — same approach as the rest of
    # the oracle. Filtering by withdrawal_credentials alone is insufficient: anyone can
    # deposit to an arbitrary pubkey using Lido's withdrawal address.
    lido_pubkeys = {key.key for key in lido_keys}

    # Lido ETH already in the CL queue at prev — deposited before the measurement window
    prev_state = w3.cc.get_state_view(prev_blockstamp)
    old_pending_deposits = Gwei(sum(
        d.amount for d in prev_state.pending_deposits
        if d.pubkey in lido_pubkeys
    ))

    # Lido ETH deposited strictly within the measurement window [prev, ref].
    # depositedForCurrentReport accumulates from the frame start (last oracle report),
    # so take the difference to exclude deposits made before prev_blockstamp — those
    # are already captured via old_pending_deposits and must not be double-counted.
    def _deposited_for_current_report(blockstamp: BlockStamp) -> Gwei:
        return wei_to_gwei(
            w3.lido_contracts.lido.functions.getBalanceStats().call(
                block_identifier=blockstamp.block_hash
            )['depositedForCurrentReport']
        )

    deposited_in_window = Gwei(
        _deposited_for_current_report(ref_blockstamp)
        - _deposited_for_current_report(prev_blockstamp)
    )

    # Lido ETH still pending in CL at ref — not yet applied, regardless of origin
    ref_state = w3.cc.get_state_view(ref_blockstamp)
    current_pending_deposits = Gwei(sum(
        d.amount for d in ref_state.pending_deposits
        if d.pubkey in lido_pubkeys
    ))

    return Gwei(deposited_in_window + old_pending_deposits - current_pending_deposits)


LIDO_V4 = 4  # version that introduced getBalanceStats / EIP-7251 top-up support

_upgrade_confirmed_at_block: int | None = None  # earliest block where version >= LIDO_V4


def _lido_version_at_block(block_number: int) -> int:
    """Returns the Lido contract version at the given EL block number.

    Caching strategy: stores the EARLIEST block number at which version >= LIDO_V4 is
    confirmed.
    - block_number >= cached value → skip RPC call, return LIDO_V4.
    - block_number <  cached value → must call (block may be pre-upgrade).
    - Pre-upgrade results are never cached.
    """
    global _upgrade_confirmed_at_block
    if (
        _upgrade_confirmed_at_block is not None
        and block_number >= _upgrade_confirmed_at_block
    ):
        return LIDO_V4  # confirmed post-upgrade, skip RPC call

    version = w3.lido_contracts.lido.functions.getContractVersion().call(
        block_identifier=block_number
    )
    if version >= LIDO_V4:
        if _upgrade_confirmed_at_block is None or block_number < _upgrade_confirmed_at_block:
            _upgrade_confirmed_at_block = block_number
    return version
```

The result supplements `validators_count_diff_in_gwei` to also account for top-ups:

```
raw_cl_rebase          = ref_balance_with_vault - prev_balance_with_vault
new_validators_capital = validators_count_diff_in_gwei(prev, ref)            ← existing, handles new validators
topup_capital          = calculate_injected_capital(prev_bs, ref_bs, …)      ← new, handles top-ups (0 in first frame)
cl_rebase              = raw_cl_rebase - new_validators_capital - topup_capital + withdrawn_from_vault
```

---

### Why the formula breaks in the first frame

`depositedForCurrentReport` is a **new counter** introduced in Lido v4.  It is initialised to 0 at upgrade time, not at the oracle report boundary.  In the first frame after the upgrade the counter starts mid-frame:

```
last_oracle_report       upgrade block                ref_blockstamp
        │                      │                             │
────────┼──────────────────────┼─────────────────────────────┤
        │                      │                             │
        │◀── deposits happen ──────────────────────────────▶ │
        │                      │                             │
        │              counter initialised = 0               │
        │              stays 0 until first oracle report     │
        │                                                    │
        │                      depositedForCurrentReport at ref = 0
```

Deposits made between `last_oracle_report` and `upgrade` land in the CL pending queue but are **not** reflected in `depositedForCurrentReport`.  The formula `deposited_in_window + old_pending − current_pending` would under-count injected capital for this frame, producing a cl_rebase that appears artificially inflated — bunker mode could fail to trigger.

### Detection and fallback

`getContractVersion()` is a plain view call.  Mainnet currently returns `3`; after the EIP-7251 upgrade it will return `4`(`LIDO_V4`).

When `_lido_version_at_block(last_report_ref_slot.block_number) < LIDO_V4`, the oracle falls back to the **pre-EIP-7251 logic**: count new validators that appeared in the window and multiply by 32 ETH.

## Known Limitation: External Deposits to Lido Validator Keys

Anyone can deposit ETH directly to a Lido validator's pubkey via the Ethereum deposit contract, bypassing Lido's own deposit mechanism (`depositBufferedEther`).

**Why the formula misses it:**

`depositedForCurrentReport` is a Lido EL contract counter — it only increments when Lido itself submits a deposit.  An external deposit to a Lido key goes through the CL pending queue (and therefore affects `old_pending_deposits` and `current_pending_deposits`) but is never reflected in `depositedForCurrentReport`.

If the external deposit is made **and applied** within the current frame, it is invisible to all three variables simultaneously:

```
old_pending_deposits      — 0  (deposited this frame, not in queue at prev_blockstamp)
deposited_in_window       — 0  (not made through Lido)
current_pending_deposits  — 0  (already applied by ref_blockstamp)
```

**Example:**

```
old_pending_deposits      = 100 ETH  (normal Lido queue from prev frame)
deposited_in_window       = 100 ETH  (Lido deposits this frame)
external deposit applied  =  10 ETH  (direct deposit to Lido validator key, this frame)
current_pending_deposits  =  10 ETH  (some Lido deposits still pending)

calculate_injected_capital = 100 + 100 − 10 = 190 ETH
actual capital injected    = 190 + 10        = 200 ETH

cl_rebase overstated by 10 ETH  ← appears as organic rewards
```
