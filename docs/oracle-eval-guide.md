# Oracle Evaluation Guide

A fork-agnostic specification for verifying that Lido oracle modules produce correct reports.
Each section describes an invariant, how to derive the expected value independently, and the
acceptance criterion. Fork-specific extensions are in separate subsections and apply only when
the corresponding EIP/fork is active.

---

## Scope

| Module | What it reports |
|--------|----------------|
| **AccountingOracle (AO)** | CL validator balances, pending deposits, vault balances, withdrawal batches, staked module balances |
| **ValidatorsExitBusOracle (VEBO)** | Ordered list of validators to exit this frame |

---

## I. Liveness invariants

These must hold at any point in time, regardless of fork.

### I-1. Frame currency

**Invariant:** `lastProcessingRefSlot == currentFrame.refSlot`

If the oracle processed the previous frame but not the current one, and the current frame's
`refSlot` is already finalized, and the deadline has not passed — that is acceptable (report
is in flight). If `lastProcessingRefSlot < currentFrame.refSlot − slotsPerFrame`, the oracle
has skipped at least one frame and is stuck.

**How to check:**
```
ao.getLastProcessingRefSlot()          → last_proc
hc.getCurrentFrame()                   → (ref_slot, deadline)
frames_behind = (ref_slot - last_proc) / slots_per_frame
```

**Acceptance criterion:** `frames_behind ≤ 1`

### I-2. Member participation

**Invariant:** At least `quorum` oracle members have submitted a vote for the current frame
by the time `refSlot` is finalized.

**How to check:**
```
hc.getMembers()                        → member addresses
hc.getConsensusStateForMember(addr)    → current_frame_report_hash (index 6)
votes = count(members where hash != 0x00...00)
quorum = hc.getQuorum()
```

**Acceptance criterion:** `votes >= quorum` after `finalized_slot >= ref_slot`

### I-3. Consensus reached before deadline

**Invariant:** `hc.getConsensusState().report != 0x00...00` before `finalized_slot > deadline`

**Acceptance criterion:** Consensus hash is non-zero; `finalized_slot <= deadline`

---

## II. AccountingOracle field invariants

All values are computed at the **reference blockstamp**: the EL block that the oracle associates
with `ref_slot`. How to resolve the reference blockstamp is described in section IV.

### II-1. `cl_validators_balance_gwei`

**Invariant:**
```
reported == sum(validator.balance
               for validator in CL_validators_at_ref_slot
               if validator.pubkey in lido_active_keys
               and validator.status starts with "active")
           + fork_balance_correction(ref_slot)   // see fork extensions
```

**Data sources:**
- Active Lido pubkeys: `GET /v1/keys?used=true` from Keys API
- Validator balances: `GET /eth/v1/beacon/states/{ref_slot}/validators?pubkeys=<list>` from CL node
- Filter to `status in {active_ongoing, active_exiting, active_slashed}`

**Acceptance criterion:** `diff == 0 gwei`

### II-2. `cl_pending_balance_gwei`

**Invariant:**
```
reported == sum(pd.amount
               for pd in CL_pending_deposits_at_ref_slot
               if pd.pubkey in lido_unused_keys)           // new validators not yet active
           + sum(pd.amount
               for active_lido_validator in active_lido_validators
               for pd in pending_deposits_for_that_validator) // top-ups to existing validators
```

**Data sources:**
- Unused Lido keys: `GET /v1/keys?used=false` from Keys API
- CL pending deposits: beacon state `pending_deposits` field (available post-Electra)
- If the chain does not have `pending_deposits`, this field is always 0

**Acceptance criterion:** `diff == 0 gwei`

### II-3. `withdrawal_vault_balance`

**Invariant:**
```
reported == eth.get_balance(locator.withdrawalVault(), block=ref_block_hash)
```

**Acceptance criterion:** `diff == 0 wei`

### II-4. `el_rewards_vault_balance`

**Invariant:**
```
reported == eth.get_balance(locator.elRewardsVault(), block=ref_block_hash)
```

**Acceptance criterion:** `diff == 0 wei`

### II-5. `shares_requested_to_burn`

**Invariant:**
```
reported == burner.getSharesRequestedToBurn(block=ref_block_hash).coverShares
          + burner.getSharesRequestedToBurn(block=ref_block_hash).nonCoverShares
```

**Acceptance criterion:** `diff == 0`

### II-6. `staking_module_ids_with_exited_validators` / `count_exited_validators_by_staking_module`

**Invariant:** For each staking module, the reported exit count equals the number of Lido
validators in that module whose CL status is `exited_*` or `withdrawal_*` at `ref_slot`,
minus the count already reported in previous frames.

**Data sources:**
- `stakingRouter.getAllStakingModules()` for module list
- `GET /eth/v1/beacon/states/{ref_slot}/validators?pubkeys=<module_keys>` per module
- `ao.getLastProcessingRefSlot()` to find the previous frame's data for delta calculation

**Acceptance criterion:** Delta counts match the actual newly-exited validators per module

### II-7. `validator_balances_gwei_by_staking_module`

**Invariant:** Sum of active validator balances per staking module, using the same methodology
as `cl_validators_balance_gwei` but broken down by module (including fork balance corrections
per module where applicable).

**Acceptance criterion:** `diff == 0 gwei` per module; total equals `cl_validators_balance_gwei`

### II-8. `is_bunker`

Bunker mode is triggered by abnormal CL rebase conditions. Full independent verification
requires replicating the bunker detection logic. A lighter check:

- `is_bunker == False` is expected when no slashing events occurred, all validators are active,
  and the CL balance change since the last report is within the normal reward range.
- If `is_bunker == True`, verify that at least one bunker trigger condition is present:
  slashing detected, negative rebase, or withdrawal rate anomaly.

**Acceptance criterion (light check):** `is_bunker == False` when no slashing events in the
`TokenRebased` log history and validator balance change is positive.

### II-9. `extra_data` (stuck keys, exiting counts)

Extra data encodes per-node-operator stuck key counts. Verify:
- `extra_data_format == EXTRA_DATA_FORMAT_EMPTY (0)` when no operators have stuck keys
- `extra_data_items_count == 0` when format is EMPTY
- If format is LIST (1 or 2), the encoded node operators actually have stuck keys on CL

**Acceptance criterion:** Format EMPTY and count 0 when all operators are healthy

### II-10. `withdrawal_finalization_batches` / `simulated_share_rate`

Non-empty batches indicate withdrawal requests were finalized this frame.

**Invariant:** If non-empty, the batch sizes sum to a value that does not exceed the ETH
available (withdrawal vault balance + EL rewards eligible for finalization). The
`simulated_share_rate` must equal the oracle's simulated rate output at the ref block.

**Acceptance criterion (light):** Batch sums ≤ `withdrawal_vault_balance`; share rate is
within 0.01% of the on-chain `stEth.getPooledEthByShares(1e27)` at ref block.

---

## III. ValidatorsExitBusOracle field invariants

### III-1. `requestsCount`

**Invariant:**
- `requestsCount == 0` when `withdrawalQueue.unfinalizedRequestNumber() == 0`
- When non-zero: the count must not exceed the number of Lido validators available to exit
  and must be consistent with the oracle's exit demand algorithm

**Acceptance criterion:** 0 when queue empty; otherwise ≤ available active Lido validators

### III-2. `dataFormat`

**Invariant:** `dataFormat == DATA_FORMAT_LIST_WITH_KEY_INDEX (2)`
Format 1 (`DATA_FORMAT_LIST`) is deprecated; format 2 encodes `(moduleId, nodeOpId, validatorIndex, keyIndex, pubkey)` per entry.

**Acceptance criterion:** `dataFormat == 2`

### III-3. Exit request entries — validator existence

**Invariant:** Each exit request entry references a validator that:
- exists on CL (pubkey matches `validatorIndex` in CL state)
- is currently `active_ongoing` or `active_exiting` (not already exited)
- belongs to the stated `moduleId` and `nodeOpId`
- has `keyIndex` matching the Keys API record for that module and operator

**Acceptance criterion:** All spot-checked entries pass all four sub-checks

### III-4. Exit priority order

**Invariant:** Within a frame, the oracle must select validators in the order defined by
`exit_order_iterator`: lowest balance first, then by validator index within equal-balance groups.
Validators from operators already below the target ratio are prioritized.

**Acceptance criterion:** If multiple exits are requested, the first N validators selected
match the top-N of the sorted priority list at ref_slot.

---

## IV. Blockstamp resolution (fork-specific)

The reference blockstamp pairs `ref_slot` (CL) with an EL block. Getting this pairing wrong
invalidates all EL-based checks (vault balances, shares to burn).

### Pre-Electra / pre-ePBS forks

```
ref_block_hash = CL_block_at_ref_slot.body.execution_payload.block_hash
ref_block_number = CL_block_at_ref_slot.body.execution_payload.block_number
```

### Post-ePBS forks (EIP-7732 / Glamsterdam)

The EL payload for slot N is not included in the CL block for slot N; only a commitment is.
The payload is revealed at slot N+1. Therefore:

```
ref_block_hash   = CL_state_at_ref_slot.latest_block_hash    // last *revealed* EL payload
ref_block_number = eth.get_block(ref_block_hash).number      // typically slot N-1's EL block
```

**Verification check:** `state.latest_block_hash == blockstamp.block_hash`

**Deposit symmetry invariant (post-ePBS only):** Deposits in the unrevealed EL payload
(blocks > ref_block) must NOT be in `CL_state.pending_deposits` at ref_slot. Both the oracle's
EL view and the CL pending_deposits list are bounded at the same `ref_block`. Any deposits
beyond that boundary appear in the next frame's `cl_pending_balance_gwei`.

**Builder indices in `payload_expected_withdrawals` (post-ePBS only):**
`payload_expected_withdrawals` may contain entries whose `validator_index` belongs to an
EL builder (not a CL validator). On known devnets builder indices start at `2^40`.
These entries must be excluded from `cl_validators_balance_gwei` and module balance calculations.
Verify that no builder index is present in the oracle's Lido validator index set.

---

## V. Verification procedure (agent task list)

Run in order. Stop at first FAIL and investigate before continuing.

```
Step 1 — Liveness
  Check I-1: frames_behind ≤ 1
  Check I-2: votes ≥ quorum (after ref_slot finalized)
  Check I-3: consensus reached, finalized_slot ≤ deadline
  FAIL condition: frames_behind ≥ 2, or zero votes after ref_slot finalized,
                  or consensus not reached before deadline passed

Step 2 — Blockstamp
  Resolve ref_block_hash for ref_slot using the active fork's method (section IV)
  Verify ref_block_hash appears in EL chain
  For post-ePBS: verify state.latest_block_hash == oracle's blockstamp.block_hash
  FAIL condition: blockstamp points to wrong EL block

Step 3 — AO numeric fields
  Check II-1: cl_validators_balance_gwei  diff == 0
  Check II-2: cl_pending_balance_gwei     diff == 0
  Check II-3: withdrawal_vault_balance    diff == 0
  Check II-4: el_rewards_vault_balance    diff == 0
  Check II-5: shares_requested_to_burn    diff == 0
  FAIL condition: any diff != 0

Step 4 — AO module fields
  Check II-6: exited validator delta counts per module
  Check II-7: per-module balance sums
  FAIL condition: mismatch between reported and independently computed counts/sums

Step 5 — AO qualitative fields
  Check II-8: is_bunker consistent with chain state (light check)
  Check II-9: extra_data format and count
  Check II-10: withdrawal batches ≤ available ETH
  FAIL condition: is_bunker=True with no triggering conditions; malformed extra_data

Step 6 — VEBO
  Check III-1: requestsCount == 0 iff queue empty
  Check III-2: dataFormat == 2
  Check III-3: spot-check up to 10 exit entries for validator existence and status
  Check III-4: first exit entry matches top of priority list at ref_slot
  FAIL condition: requestsCount inconsistent, wrong dataFormat, unknown pubkeys,
                  or wrong exit order

Step 7 — Trend check (last 3 frames)
  cl_validators_balance_gwei must be non-decreasing unless a withdrawal batch occurred
  FAIL condition: unexplained balance drop > 0.1 ETH between consecutive frames
```

---

## VI. Data sources reference

| Data | Source |
|------|--------|
| CL validator state at slot | `GET /eth/v1/beacon/states/{slot}/validators` |
| CL pending deposits | `GET /eth/v2/debug/beacon/states/{slot}` → `pending_deposits` |
| CL latest block hash (post-ePBS) | same debug state → `latest_block_hash` |
| CL payload expected withdrawals | same debug state → `payload_expected_withdrawals` |
| EL block by hash | `eth_getBlockByHash` |
| ETH balance at block | `eth_getBalance(addr, block_hash)` |
| Lido key registry | `GET /v1/keys?used=true` and `?used=false` from Keys API |
| Staking module list | `stakingRouter.getAllStakingModules()` |
| AO last processed slot | `accountingOracle.getLastProcessingRefSlot()` |
| VEBO last processed slot | `validatorsExitBusOracle.getLastProcessingRefSlot()` |
| Consensus state | `hashConsensus.getConsensusState()` |
| Member states | `hashConsensus.getConsensusStateForMember(addr)` |
| Burner shares | `burner.getSharesRequestedToBurn()` |
| Withdrawal queue depth | `withdrawalQueue.unfinalizedRequestNumber()` |
| AO report calldata | find `ProcessingStarted(ref_slot)` event on AO → get tx → decode input |
| VEBO report calldata | find `ProcessingStarted(ref_slot)` event on VEBO → get tx → decode input |
