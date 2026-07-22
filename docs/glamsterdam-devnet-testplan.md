# Glamsterdam (Gloas) Oracle — Devnet Test Plan

Manual test plan for validating the lido-oracle Glamsterdam (EIP-7732 / EIP-8061 / EIP-7917)
changes against a Lido-run devnet with Gloas active. These scenarios cover behavior that cannot
be exercised by unit tests: real beacon-API response shapes, empty (payload-withheld) slots,
on-chain deposit reconciliation, and CL-client endpoint differences.

The corresponding off-chain changes ship across four branches/tickets:

| Ticket | Change | Branch |
|---|---|---|
| T1 | BlockStamp EL-anchor + pending-deposit resolution under ePBS | `feat/gloas-blockstamp-infra` |
| T2 | Accounting conditional in-flight withdrawal TVL correction | `feat/gloas-accounting-tvl` |
| T3 | Ejector sweep-delay + EIP-8061 exit churn limit | `feat/gloas-ejector` |
| T4 | Proposer-duties v2 endpoint with relaxed v1 fallback | `feat/gloas-proposer-duties-v2` |

> Run every scenario against a build that contains **all four** branches merged (e.g. an
> integration branch), so cross-cutting behavior is exercised together.

## 0. Assumptions to confirm before starting

These are flagged in the implementation as "confirm against final spec / real node". Verify each
against the devnet's CL client **before** trusting scenario results:

- The beacon config `/eth/v1/config/spec` announces the Gloas fork-epoch field the oracle reads
  (`GLOAS_FORK_EPOCH` in `src/providers/consensus/types.py::BeaconSpecResponse`). If the client
  uses a different key, `is_gloas` stays `False` and every Gloas path is silently skipped — update
  the field name first.
- `GET /eth/v2/debug/beacon/states/{id}` returns `latest_block_hash` and
  `payload_expected_withdrawals` at the top level, and each `payload_expected_withdrawals` entry has
  `validator_index` and `amount`.
- `GET /eth/v2/beacon/blocks/{id}` post-fork returns a body with **no** `execution_payload` and with
  `signed_execution_payload_bid.message.block_hash`.

If any field name/shape differs, fix the dataclass in `src/providers/consensus/types.py` and the
resolver in `src/utils/blockstamp.py` before proceeding — the unit tests are shape-agnostic and will
not catch a wrong key.

## 1. Environment setup

1. Point the oracle at the Gloas devnet:
   - `EXECUTION_CLIENT_URI`, `CONSENSUS_CLIENT_URI`, `KEYS_API_URI`
   - `LIDO_LOCATOR_ADDRESS` for the devnet deployment
2. Set `DAEMON=False` to run each module once (one-shot) so a scenario maps to a single report.
3. Ensure the devnet's `GLOAS_FORK_EPOCH` is in the past (fork already activated) before running
   report scenarios; for the pre-fork regression check (Scenario 0b) use a ref slot before the fork.
4. Prepare a member key (`MEMBER_PRIV_KEY`) only if testing on-chain submission; otherwise run in
   dry-run to inspect the computed report.

### Scenario 0b — Pre-fork regression (sanity)

Run the accounting and ejector modules on a **pre-fork** ref slot.
- **Expect:** blockstamp built exactly as before (EL anchor = the block's own embedded
  `execution_payload`); `withdrawal_correction_needed = False`; no `get_state_latest_block_hash`
  calls; churn/sweep identical to the current production oracle. Confirms the fork gate is inert
  before activation.

## 2. Scenario A — ref_slot payload confirmed full (Y == ref_slot)

Pick a ref slot whose own execution payload was revealed and confirmed before the payload deadline
(the common case).

Steps:
1. Run the accounting module one-shot for this frame.
2. Inspect logs / computed report.

Expect:
- The blockstamp's `block_hash` (Y) equals ref_slot's own execution block hash;
  `withdrawal_correction_needed = False`.
- **No** withdrawal correction applied at any of the four call sites (log line
  `Gloas in-flight withdrawal correction` is absent).
- `pending_deposits` read from ref_slot's child state include any deposits that landed in
  ref_slot's own payload.
- Report submits (or dry-run computes) with **no** `OracleReportSanityChecker` revert.

## 3. Scenario B — ref_slot payload withheld (Y < ref_slot)

Reproduce (or wait for) a slot whose own payload was not confirmed by the deadline (an "empty"
slot). On a devnet this can be induced by delaying/withholding the builder payload for a target
slot, then choosing that slot as the report ref slot.

Expect:
- Blockstamp `block_hash` (Y) resolves to the last confirmed EL block **before** ref_slot;
  `withdrawal_correction_needed = True`.
- The `Gloas in-flight withdrawal correction` add-back is applied to: total CL balance, the
  per-module breakdown, the bunker-mode reference balance, and staking-vault total value.
- The per-module balance sum **equals** the reported total CL balance (the on-chain equality
  invariant `AccountingOracle` enforces).
- TVL matches the independently computed expectation (CL balances at ref_slot **plus** the
  in-flight withdrawal amount, since the EL vault has not yet been credited).

## 4. Scenario C — Lido deposit lands in ref_slot's own payload

Trigger a Lido deposit so it is included in ref_slot's own execution payload.

Expect:
- The oracle's `postCLPendingBalance` reconciles with `Lido.sol`'s live deposit counter (the
  deposit is visible because `pending_deposits` is read from ref_slot's child state).
- The `AccountingOracle` report does **not** revert in
  `_checkCLPendingBalanceAndCalculateMaxPossibleActivatedBalance`.
- Run this in both the Scenario A (payload full) and Scenario B (payload withheld) conditions.

## 5. Scenario D — Ejector churn and sweep

Run the ejector module one-shot post-fork with a non-trivial withdrawal-queue demand.

Expect:
- Exit-churn prediction uses `get_exit_churn_limit` (EIP-8061): at the devnet's total active stake,
  the per-epoch churn is ~`total_active_balance / 2**15` (uncapped), roughly 5x the pre-fork capped
  value; the predicted `withdrawal_epoch` is correspondingly shorter.
- The sweep-delay projection **excludes** `pending_partial_withdrawals`: inject some EIP-7002
  partial-withdrawal requests and confirm the predicted delay does not shrink because of them.
- The number of validators queued for exit meets (or slightly exceeds) what the withdrawal queue
  needs — confirm it does **not** under-eject relative to the pre-fork oracle for the same demand.
- Confirm `_get_total_el_balance` / `_get_deposit_lock_amount` read EL balances at Y consistently
  (compare against a direct `eth_getBalance` at Y for the vaults).

## 6. Scenario E — Proposer-duties endpoint compatibility

Run the performance collector against CL clients with and without the v2 duties endpoint.

- **Node with v2** (e.g. Lighthouse/Teku that shipped beacon-APIs#563): duties fetched from
  `/eth/v2/validator/duties/proposer`; `dependent_root` validated strictly against the last slot of
  epoch-2; a deliberate mismatch (point at a slightly-out-of-sync node) is **fatal**.
- **Node without v2** (e.g. Nimbus): the collector receives 404 for v2 and falls back to v1; a
  `dependent_root` mismatch on the v1 path is **logged as a warning, not fatal**, and collection
  proceeds. Confirm the warning appears and no checkpoint is dropped.

## 7. Cross-module consistency

Run accounting, ejector, and CSM for the same frame/ref slot.
- **Expect:** all three observe the same `ref_slot`, the same resolved EL anchor Y, and the same
  `pending_deposits` (all inherit the shared blockstamp from `get_blockstamp_for_report`).

## 8. Liveness / edge cases

- **Child not finalized:** attempt a report where ref_slot's child block is not yet finalized.
  Expect the module to log "Reference slot's child is not yet finalized." and wait (no crash, no
  partial report), then succeed once the child finalizes.
- **Missed child slots:** choose a ref slot followed by one or more entirely missed CL slots.
  Expect the child resolver to walk forward to the first actual block.
- **Head/finalized liveness blockstamps:** confirm the daemon's finalized stamp and the report
  path's head stamp resolve their EL anchor via the block's own `latest_block_hash` (streamed),
  and that `get_member_info` EL calls at the head block succeed.

## Pass/fail summary

A scenario **passes** only if every "Expect" bullet holds. Record for each scenario: ref slot, Y,
`withdrawal_correction_needed`, whether a report submitted without revert, and any log anomalies.
Any revert, TVL mismatch, under-ejection, or fatal proposer-duties error is a **fail** and must be
triaged before mainnet activation.
