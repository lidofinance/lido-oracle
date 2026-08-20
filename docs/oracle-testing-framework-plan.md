# Oracle Testing Framework — Plan & Scenario Catalogue (Glamsterdam)

> Status (2026-07-22): **Layer 1 is active; Layer 2 is active for accounting and EJ-02**. Layer-1
> ejector and accounting scenarios live in `tests/scenarios/`; AC-01, synthetic AC-02–AC-05,
> AC-10, and the real-devnet EJ-02 cassette run through Layer 2 from portable CL/KAPI cassettes
> and self-contained EL archives. Layer 3 remains proposed.
> This document answers the three goals in
> `lido-oracle-glamsterdam-testplan-spec.md`: (1) established scenarios, (2) framework
> architecture, (3) testplan/runbook architecture — with a concrete Glamsterdam instantiation for
> the **accounting** and **ejector** modules.
>
> **Companion runbook:** `docs/glamsterdam-devnet-scenario-setup.md` — how to use lido-cli against the
> live devnet and drive deposits/withdrawals/toggles into the states these scenarios need, then record
> cassettes. Read both together.

---

## 0. TL;DR

- **The core problem.** Oracle correctness is a function of four things at once:
  `correctness = f(ref-slot timing, CL state shape, EL state, Lido contract state)`. Our unit
  tests mock all four away, so they are *shape-agnostic* — they cannot catch a wrong beacon-API
  key, a withheld-payload edge case, or an on-chain sanity-checker revert. The existing fork tests
  exercise the real submit path but only assert "a report was processed", never the report's
  contents, and they run on **real pre-fork mainnet CL data** so they cannot reproduce any
  Glamsterdam CL shape.
- **The proposal.** A three-layer pyramid driven by a single declarative **Scenario** definition,
  glued together by a **recorded CL/EL fixture corpus ("cassettes")**:
  1. **Layer 1 — Report-golden scenario tests** (offline, deterministic, CI-default, seconds).
     Build the *full* report from recorded fixtures and assert every field + on-chain invariants.
     This is the new layer that closes the biggest gap.
  2. **Layer 2 — Anvil-fork e2e** (extends `tests/fork/`, minutes). Real HashConsensus → submit →
     sanity-checker path against forked EL, now asserting report **content** and fed Glamsterdam CL
     shapes via the same cassettes.
  3. **Layer 3 — Devnet acceptance** (self-hosted ePBS / Kurtosis Glamsterdam, slow, pre-release
     gate). The only layer that produces *real* Gloas CL state; it also **records the cassettes**
     that Layers 1–2 replay, keeping them shape-faithful.
- **Fast local loop.** A developer runs Layer 1 in seconds with no network, and Layer 2 in a couple
  of minutes with only an EL/CL RPC. Layer 3 is reserved for the pre-release gate and cassette
  refresh, minimizing cross-team coordination.
- **Key decision to confirm.** Whether a recorded-cassette corpus is acceptable as the CI source of
  truth (my recommendation) vs. requiring a live CL for all integration tests. See §12.

---

## 1. Problem restatement

The oracle is a timing- and state-driven system. A report is only correct relative to:

| Axis | What varies | Why it matters |
|---|---|---|
| Ref-slot timing | Which slot the frame resolves to; finality of its child; missed slots | Frame boundaries tie off-chain view to on-chain nonces (`HashConsensus.refSlot(K) = frameStartSlot(K) − 1`) |
| CL state shape | Beacon-API response *shape* + values (validators, balances, withdrawals, block body) | Glamsterdam changes the block-body shape (no embedded `execution_payload`) and adds builder entries; wrong parsing silently skips Gloas paths |
| EL state | Vault balances, deposit contract, EL block chosen as anchor Y | TVL identity and deposit reconciliation depend on which EL block anchors the frame |
| Lido contract state | Consensus version, sanity-checker limits, bunker allowance, paused queues | Determines whether a *computed* report is even *accepted* on-chain |

A useful testing framework must be able to **hold three axes fixed and vary one**, deterministically.
That is the design constraint everything below serves.

---

## 2. What exists today (gap analysis)

| Capability | Today | Gap |
|---|---|---|
| Per-service unit tests (bunker, safe_border, withdrawal, prediction, sweep, exit-order, extra-data, data-encode) | ✅ Strong, `@pytest.mark.unit`, network blocked | Shape-agnostic; mock the CL/EL entirely |
| Polyfactory fixtures for blockstamps/validators/configs | ✅ `tests/factory/*` | No factory or golden for the **`ReportData` tuple** itself |
| Full report built end-to-end, all fields asserted | ❌ Unit tests mock `_calculate_report`; nothing asserts the tuple | **Primary gap** — no report-golden test |
| Recorded CL/EL/KAPI response corpus (cassettes/VCR/JSON) | ✅ Versioned cassettes under `tests/cassettes/` | More real devnet frames and module refresh automation are still needed |
| Anvil-fork e2e that submits on-chain | ✅ `tests/fork/` forks EL, patches real CL, drives `cycle_handler()` | Asserts only `last_processing_ref_slot`; **no content assertions**; CL is real **pre-fork mainnet** |
| Ability to inject Glamsterdam CL shapes (withheld payload, builder withdrawals) | ✅ Recorded cassettes + provenance-locked synthetic overlays | More production-derived frames are still needed |
| Real Gloas CL in the loop | ⚠️ ePBS devnet exists, but **released oracle crashes** (`BeaconBlockBody missing execution_payload`) | This branch (`feat/gloas-devnet`) is the fix — needs a gate that proves it |
| Scenario visualization / reviewable results | ❌ | Requested; nothing today |
| `tests/e2e/` | ❌ Empty placeholder | — |

**Injection seam (important):** the single point where a report's inputs enter is
`ConsensusModule.get_blockstamp_for_report` → `BlockstampBuilder.get_reference_blockstamp`, plus the
`cc` (consensus client), `kac` (keys API) and EL provider attached to the `web3` object. Every layer
below injects at this seam — either by swapping `cc`/`kac` for cassette-backed replays (Layers 1–2)
or by pointing at real nodes (Layer 3).

---

## 3. Design principles

1. **Every iteration verifies correctness.** Adding/removing a scenario must never weaken the
   invariant checks. Invariants (below) are enforced by the harness, not by individual scenarios.
2. **Vary one axis at a time.** The harness fixes timing/CL/EL/contract independently.
3. **Fast by default, real when it counts.** The inner loop is offline; real devnet is a gate, not a
   dev dependency.
4. **One scenario definition, multiple layers.** A scenario is declared once and can run at whichever
   layers it is meaningful for. This is what keeps the framework flexible per the spec's Rules.
5. **Fixtures must be real.** Cassettes are *recorded from a real Gloas devnet*, never hand-written,
   so Layer 1 stays shape-faithful. Drift is caught because Layer 3 re-records and Layer 2 replays.
6. **Assert invariants, not just values.** Golden values catch regressions; invariants catch classes
   of bugs (see §5.3).

---

## 4. Architecture — the three-layer pyramid

```
                 ┌───────────────────────────────────────────────┐
   slow / gate   │  L3  DEVNET ACCEPTANCE                          │  real Gloas CL + EL + contracts
   pre-release   │  self-hosted ePBS / Kurtosis glamsterdam        │  lido-cli drives ops, assertoor asserts
                 │  ── records cassettes ──▲──────────────────────┘  → produces the corpus below
                 └───────────────────────┼─────────────────────────
   minutes       ┌───────────────────────┼─────────────────────────┐
   CI + local    │  L2  ANVIL-FORK E2E    │                         │  forked EL (real Lido contracts) +
                 │  extends tests/fork/   │  replays cassettes as CL │  replayed/patched CL; real submit path
                 └───────────────────────┼─────────────────────────┘  → asserts report CONTENT + on-chain accept
   seconds       ┌───────────────────────┼─────────────────────────┐
   CI-default    │  L1  REPORT-GOLDEN     ▼                         │  no network; cassette-backed cc/kac/EL
   local inner   │  build full report, assert every field + inv.   │  → asserts ReportData tuple + invariants
                 └─────────────────────────────────────────────────┘
        ▲ connective tissue: the CASSETTE CORPUS + the SCENARIO definition (§5)
```

### 4.0 Layer-selection principle (which layer verifies a scenario)

The discriminator is **not** "complex/many-field → L2, simple → L1". Layer 1 already asserts the *full*
report tuple against a golden (all 19 accounting / 5 ejector fields), so field count alone never forces
a scenario up to L2. The real question is **what kind of correctness is at stake**:

> **Layer 1** — everything the oracle *computes off-chain*: the full `ReportData` tuple, the off-chain
> invariants (§5.3), and simple contract-flag gates the oracle merely *reads* (pause, submitted).
> **Layer 2** — everything about whether that report is *accepted on-chain* or *depends on a live
> contract computation* that L1 cannot reproduce: sanity-checker no-revert (per-module balance
> equality, deposit reconciliation), fields sourced from on-chain simulation
> (`finalization_share_rate` via `calculate_finalization_batches`), and the HashConsensus quorum +
> calldata round-trip.

Consequences worth internalizing:
- A complex accounting report goes to L2 **because its on-chain acceptance is the risk** (the sanity
  checker's strict equalities), not because it has many fields. That is why the heuristic "complex →
  L2" usually lands correctly — the correlation is real but the *cause* is acceptance risk.
- A scenario can split **across layers by branch**. AC-06's empty branches (paused / no-unfinalized /
  no-ETH) are pure L1 flag checks; only its normal branch is L2-worthy because `finalization_share_rate`
  comes from on-chain simulation.
- A gate that prevents submission entirely (VEBO paused → no report, EJ-08) has *no* on-chain
  acceptance to test, so it is **L1 only** — the oracle's handling of the flag is the logic; whether the
  contract actually pauses is not the oracle's concern.

### 4.1 Layer 1 — Report-golden scenario tests (the new layer)

- **What.** Instantiate `Accounting(web3)` / `Ejector(web3)` with a `web3` whose `cc`, `kac`, and EL
  provider are **cassette-backed replays** (no sockets). Force the ref slot via a stubbed
  `get_member_info` / frame config. Call `build_report(blockstamp)` and assert the **entire
  `ReportData` tuple** against a checked-in golden, plus the invariants in §5.3.
- **Why it closes the gap.** It is the only place we assert what the oracle actually *computes*, and
  because the CL/EL inputs are *recorded real responses*, it catches shape bugs (a renamed
  `GLOAS_FORK_EPOCH` field, a missing `payload_expected_withdrawals` key) that unit mocks cannot.
- **Speed.** Milliseconds–seconds. Runs in the default `-m unit`-style CI job (new marker,
  `@pytest.mark.scenario`, still network-blocked).
- **Mechanics.** Reuse the polyfactory layer for *contract* return values that are cheap to fake
  (sanity-checker limits, simulation results) and cassettes for the *CL/EL response corpus* that must
  be shape-faithful. IPFS publish is stubbed (fixed CID), as it already is in the fork harness.
- **Coverage target.** Every scenario in §9–§10 that does not strictly require an on-chain submission.

### 4.2 Layer 2 — Anvil-fork e2e (extend existing harness)

- **What.** Keep `tests/fork/conftest.py`'s anvil-EL-fork + fresh-HashConsensus + oracle-member
  machinery. Two upgrades:
  1. **Assert content, not just processing.** After `cycle_handler()` submits, read back the
     submitted report (event/calldata) and compare to the scenario's expected tuple; assert the
     on-chain sanity checker **accepted** it (no revert), which is the real value of this layer.
  2. **Feed Glamsterdam CL shapes.** Generalize `PatchedConsensusClient` so its CL source can be a
     **cassette replay** instead of (or layered over) the live mainnet CL. This lets Layer 2 run the
     withheld-payload / builder-withdrawal / EIP-8061-churn scenarios that real mainnet cannot
     produce, while still exercising the true EL contracts and submit path.
- **Why.** Layer 1 proves "the number is right"; Layer 2 proves "the chain accepts it" — including
  the strict per-module-balance equality the `OracleReportSanityChecker` enforces, and the
  `_checkCLPendingBalanceAndCalculateMaxPossibleActivatedBalance` deposit reconciliation.
- **Speed.** Anvil boots ~5s; a cycle is minutes. Runs in the existing `mainnet_fork_tests.yml`-style
  CI job (self-skips when mixed with other tests — keep that).
- **Constraint.** Anvil is **EL-only**; the CL always comes from a cassette or a real node. This is
  already the harness's design and we lean into it.
- **Devnet lifetime.** A Layer-2 scenario does not depend on the source devnet after refresh. The
  checked-in cassette owns the CL/KAPI responses and execution headers; a compact Anvil archive owns
  all contract code and storage touched at the execution anchor. `scripts/refresh_oracle_scenario.py`
  records both from any network config. Normal Layer-2 runs use `--load-state` and make no public RPC
  calls. Goldens and synthetic overlays are never silently rewritten during refresh because those
  are reviewed expectations, not observations.

### 4.3 Layer 3 — Devnet acceptance (the reality gate + cassette source)

- **What.** Run the actual daemon (`DAEMON=False`, one-shot per scenario) against a **self-hosted
  ePBS stand** (`lido-local-devnet stands epbs`, Gloas fork epoch 5) or a local **Kurtosis
  `glamsterdam-devnet`** preset. Drive scenario setup with **lido-cli** (deposits, voluntary exits,
  EIP-7002 withdrawal/consolidation requests, `devnet replace-dsm-with-eoa`) and assert with a thin
  pytest acceptance suite + **assertoor** playbooks for chain/beacon-state assertions.
- **Why it's indispensable.** It is the only layer with *real* Gloas CL state and real finality, so
  it is where we (a) prove the branch no longer crashes (`BeaconBlockBody missing execution_payload`),
  (b) validate that Layer 1/2 cassettes are faithful, and (c) run the manual runbook (§8).
- **Milestone-0 gate.** "The `feat/gloas-devnet` build runs accounting + ejector one-shot against the
  ePBS devnet and produces a valid report without crashing." Everything else builds on that.
- **Cassette recording.** A small `record` mode wraps the real `cc`/`kac`/EL clients and serializes
  every response for a chosen ref slot into a cassette. That cassette becomes a Layer 1/2 fixture.

### 4.4 The connective tissue

- **Cassette corpus** (`tests/cassettes/<network>/<scenario-id>/`): recorded CL block/state/header,
  KAPI keys, EL blocks/balances for a specific ref slot. Recorded at Layer 3, replayed at Layers 1–2.
  Versioned; each carries the fork-spec (`/eth/v1/config/spec`) it was recorded against so a spec
  change invalidates stale cassettes loudly.
- **Scenario definition** (§5): the single declarative object each layer consumes.

---

## 5. The Scenario abstraction

### 5.1 Shape

A scenario is a declarative object (a dataclass / YAML) — *given/when/then*:

```
Scenario:
  id: "AC-03-fallback-withheld-payload"
  module: accounting | ejector
  gloas_area: blockstamp | tvl | churn-sweep | builder-mask | baseline
  given:
    cassette: "epbs-devnet/ac-03"          # CL/EL/KAPI corpus (L1/L2)
    ref_slot_condition: payload_withheld    # how to pick/force the ref slot
    contract_state:                         # sanity limits, bunker allowance, paused flags
      allow_reporting_in_bunker: false
    devnet_setup:                           # L3 only: lido-cli steps to reach `given`
      - "elr withdrawal-request <pubkey> <amount>"
  when: run <module> one-shot for the frame
  then:
    report_fields: { withdrawal_correction_needed: true, is_bunker: false, ... }
    invariants: [per_module_sum_equals_total, no_sanity_revert, tvl_matches_independent]
  layers: [L1, L2, L3]
```

### 5.2 Why one definition for three layers

- The `then.invariants` are shared; only the *driver* differs (cassette replay vs. real submit vs.
  live devnet). Adding a scenario = adding one object; deleting = removing it. The invariant set is
  the framework's correctness floor and is independent of the scenario list — satisfying the spec's
  "flexible but always verifies correctness" rule.

### 5.3 Invariant library (enforced regardless of scenario)

- **Per-module equality:** `Σ validator_balances_gwei_by_staking_module == cl_validators_balance_gwei`
  (the on-chain revert condition in §2 of the changes doc).
- **TVL identity:** independently recomputed TVL (CL balances at ref + in-flight W in the fallback
  case) equals the report's implied TVL.
- **Deposit reconciliation:** off-chain `postCLPendingBalance` matches `Lido.sol`'s deposit counter at
  the ref slot (no `_checkCLPendingBalance…` revert).
- **No sanity-checker revert** (Layers 2–3).
- **Ejector never under-ejects:** ejected balance + predictable EL balance ≥ `unfinalized_steth`.
- **Fork-gate inertness:** on a pre-fork ref slot, all Gloas paths are inert (regression guard).
- **Blockstamp consistency across modules:** accounting/ejector/csm share ref slot, EL anchor Y, and
  `pending_deposits` for the same frame.

---

## 6. Technology choices & rationale

| Concern | Choice | Rationale | Rejected alternative |
|---|---|---|---|
| Test runner | **pytest** (existing), new markers `@pytest.mark.scenario` (L1) reusing `fork` (L2) | Zero new tooling; marker discipline already enforced | A bespoke runner — needless |
| Offline CL/EL replay | **Recorded cassette corpus** (JSON per response), thin replay client subclassing `ConsensusClient` (mirrors `PatchedConsensusClient`) | Shape-faithful + deterministic + no network; extends a pattern already in the repo | VCR.py — heavier, HTTP-level, awkward for the multi-provider stack; hand-written JSON — not shape-faithful |
| EL fork | **anvil** (`-f <EL RPC> --fork-block-number N --auto-impersonate`) | Already used in `tests/fork/`; ~5s boot; cheat codes for storage/balance/impersonation | hardhat node — slower, already avoided in this repo |
| Protocol ops driver | **lido-cli** (`elr`, `validators`, `lido`, `dsm`, `devnet`) | Already the devnet's own driver; covers deposits, exits, EIP-7002 requests | Hand-rolled web3 scripts — duplicates lido-cli |
| Devnet | **lido-local-devnet** ePBS self-hosted stand (Gloas epoch 5) + Kurtosis `glamsterdam-devnet` preset | The only genuine-Gloas paths that exist; ePBS is documented | Full custom genesis — reinvents lido-local-devnet |
| On-chain/beacon assertions on devnet | **assertoor** playbooks + thin pytest acceptance suite | assertoor is already wired (`lido-local-devnet assertoor up`) and speaks CL+EL | Manual only — the status quo we're replacing |
| Visualization | **pytest-html / pytest-json → static HTML dashboard**, optionally published as an Artifact | Cheap, CI-friendly, matches "visualise scenarios and results" | A full web app — overkill |

---

## 7. Visualization

Two outputs, both cheap:

1. **Scenario matrix** — a generated table (module × Gloas-area × layer coverage × pass/fail),
   rendered from the scenario definitions so it never drifts from the code.
2. **Run report** — pytest-json → a single self-contained HTML page: per-scenario given/when/then,
   the expected-vs-actual `ReportData` diff, invariant pass/fail, and the ref slot / Y / correction
   flags recorded (exactly the fields the manual runbook asks operators to record). Publishable as a
   shareable Artifact for review.

---

## 8. Testplan / runbook architecture

The manual runbook is **generated from the same scenario definitions**, so the automated suite and
the operator runbook never diverge. Each scenario renders to a runbook section:

- **Preconditions** (from `given.contract_state` + `given.devnet_setup`).
- **Steps** (the `lido-cli` / assertoor commands to reach `given`, then run the module one-shot).
- **Expected** (the `then` bullets, verbatim).
- **Record** (ref slot, Y, `withdrawal_correction_needed`, submitted-without-revert, log anomalies).

The existing `docs/glamsterdam-devnet-testplan.md` (scenarios A–E) becomes the first generated
output; its scenarios map 1:1 onto §9–§10 below. Pass/fail rule is unchanged: a scenario passes only
if every `Expect`/invariant holds; any revert, TVL mismatch, under-ejection, or fatal duties error is
a fail and blocks mainnet activation.

---

## 9. Scenario catalogue — ACCOUNTING

Report tuple under test (19 fields): `consensus_version, ref_slot, cl_validators_balance_gwei,
cl_pending_balance_gwei, staking_module_ids_with_exited_validators,
count_exited_validators_by_staking_module, staking_module_ids_with_updated_balance,
validator_balances_gwei_by_staking_module, withdrawal_vault_balance, el_rewards_vault_balance,
shares_requested_to_burn, withdrawal_finalization_batches, finalization_share_rate, is_bunker,
vaults_tree_root, vaults_tree_cid, extra_data_format, extra_data_hash, extra_data_items_count`.

| ID | Given | Then (key assertions) | Layers | Area |
|---|---|---|---|---|
| **AC-00** | Pre-fork ref slot | Blockstamp built as before (EL anchor = own payload); `withdrawal_correction_needed=False`; no `get_state_latest_block_hash` calls; churn/sweep identical to prod. Fork gate inert. | L1,L2 | baseline |
| **AC-01** | Standard post-fork frame, payload **confirmed** (Y==ref_slot), no bunker, no vaults | Full tuple matches golden; **no** correction log; deposits in N's own payload present in `cl_pending_balance_gwei`; per-module sum == total. | L1,L2 | blockstamp/primary |
| **AC-02** | Payload **withheld** (Y<ref_slot), in-flight Lido withdrawals present | `withdrawal_correction_needed=True`; add-back applied to total CL balance **and** per-module breakdown **and** bunker reference; per-module sum == total; TVL == CL@ref + W. | L1,L2 | tvl/fallback |
| **AC-03** | Withheld payload + `payload_expected_withdrawals` contains **builder** entries (`validator_index ≥ 2^40`) | No `IndexError`; builder entries excluded from the Lido-only correction; total unaffected by builders. | L1 | builder-mask |
| **AC-04** | Fallback case + large withdrawal batch at ref slot | Bunker abnormal-rebase detector uses the mirrored correction → **no spurious** negative rebase → `is_bunker=False`. | L1,L2 | tvl/bunker |
| **AC-05** | True negative-rebase / slashing condition | `is_bunker=True`; if `ALLOW_REPORTING_IN_BUNKER_MODE=False` → report **not** submitted (L2); safe border switches to the earlier negative-rebase/associated-slashing variant. With queued requests this can change `withdrawal_finalization_batches`. | L1,L2 | bunker/safe-border |
| **AC-06** | Withdrawal queue: (a) paused, (b) no unfinalized requests, (c) no available ETH, (d) normal | (a)-(c) → empty `withdrawal_finalization_batches`; (d) → non-empty, `finalization_share_rate` from on-chain simulation. **✅ (a)-(c) covered at L1** — `tests/modules/accounting/test_withdrawal_unit.py::{test_returns_empty_batch_if_paused, test_returns_empty_batch_if_there_is_no_requests, test_no_available_eth_to_cover_wc}` (simple flag/early-return checks, per §4.0). (d) belongs at L2 (on-chain `calculate_finalization_batches`). | L1 (a-c) / L2 (d) | withdrawal |
| **AC-07** | Newly exited validators: (a) none, (b) one item, (c) exceeds `max_items_per_extra_data_transaction` | (a) `extra_data_format=EMPTY`, items_count=0; (b) NON_EMPTY, correct hash; (c) multi-tx batching, phase-3 `_submit_extra_data` loops. | L1,L2 | extra-data |
| **AC-08** | Lido deposit lands in ref-slot's **own** payload (primary case) | `postCLPendingBalance` reconciles with `Lido.sol` counter; **no** `_checkCLPendingBalance…` revert. Run under both AC-01 and AC-02 conditions. | L2,L3 | deposit-reconcile |
| **AC-09** | Staking vaults present | Vault tree built + published (mocked CID in L1/L2, real in L3); `vaults_tree_root`/`vaults_tree_cid` populated; absent → `(ZERO_HASH, '')`. | L1,L3 | vaults |
| **AC-10** | Child of ref slot **not yet finalized**; and: ≥1 missed child slots | Logs "child is not yet finalized", waits, then succeeds; resolver walks forward to first real block. | L2,L3 | liveness |
| **AC-11** | Same frame run for accounting + ejector (+ csm) | All observe same `ref_slot`, same EL anchor Y, same `pending_deposits`. | L1,L2,L3 | cross-module |

### Decision branches explicitly covered
bunker on/off × safe-border variant × withdrawal-finalization edge cases × extra-data empty/one/multi
× vaults present/absent × Gloas primary/fallback × builder entries present/absent.

---

## 10. Scenario catalogue — EJECTOR

Report tuple under test (5 fields): `consensus_version, ref_slot, requests_count, data_format, data`.
`data` packs, per validator sorted by `(module_id, no_id, validator.index)`:
`moduleId(3) | nodeOpId(5) | validatorIndex(8) | keyIndex(8) | pubkey(48)`.

| ID | Given | Then (key assertions) | Layers | Area |
|---|---|---|---|---|
| **EJ-00** | Pre-fork ref slot, standard demand | Churn uses `get_activation_exit_churn_limit`; sweep formula pre-fork; report matches golden. Fork gate inert. | L1,L2 | baseline |
| **EJ-01** | Post-fork, `unfinalized_steth` demand > predictable EL balance | Validators selected until ejected + predictable EL ≥ demand; `data` byte-exact + correctly sorted; `requests_count` matches. | L1,L2 | selection/encode |
| **EJ-02** | `unfinalized_steth` ≤ predictable EL balance | Eject list empty **except** forced validators (`get_remaining_forced_validators`). | L1 | selection |
| **EJ-03** | Post-fork, non-trivial demand | Churn uses `get_exit_churn_limit` (EIP-8061) ≈ `total_active_balance / 2**15` (uncapped, ~5× pre-fork); predicted `withdrawable_epoch` shorter; ejects **≥** pre-fork oracle for same demand. | L1,L2,L3 | churn (EIP-8061) |
| **EJ-04** | Inject a flood of EIP-7002 `pending_partial_withdrawals` | Sweep-delay projection **excludes** partials from numerator **and** denominator → predicted delay does **not** inflate → ejector does **not** under-eject. Compare against a "naive-included" control to prove the fix. | L1,L2,L3 | sweep (EIP-7002 attack) |
| **EJ-05** | ~~`builder_pending_withdrawals` present~~ | **Dropped (design decision).** `builder_pending_withdrawals` was deliberately *not* folded into the sweep projection; there is no field or denominator adjustment in `sweep.py`, so there is nothing to assert. Not a gap. | — | sweep |
| **EJ-06** | Forced validators pending regardless of demand | Always appended after the fill loop. | L1 | selection |
| **EJ-07** | Node-operator weights not yet updated | `WeightsNotUpdatedError` → defer, **no** report this cycle; succeeds next finalized epoch. | L1,L2 | liveness |
| **EJ-08** | VEBO paused | `is_reporting_allowed=False` → no report. **✅ covered at L1** — `tests/modules/ejector/test_ejector.py::{test_ejector_execute_module_on_pause, test_is_reporting_allowed__reflects_pause_state}`. **L1 only** by §4.0: a gate that prevents submission has no on-chain acceptance to test. | L1 | contract-state |
| **EJ-09** | Builder-registry entry (index ≥ `2^40`) present in CL state alongside Lido validators | ✅ Builder entry never enters the eject list: `compute_lido_validators` is a **pubkey-keyed intersection** of KAPI used-keys with the CL registry, so no builder pubkey matches and no `2^40`-flagged index ever reaches a `state.validators[...]` lookup. Safety is structural (key filter), not index-masking. | L1 | builder-mask |
| **EJ-10** | Post-fork frame with vaults + withdrawal reserve | `_get_total_el_balance` / `_get_deposit_lock_amount` read EL balances at Y; cross-check vs direct `eth_getBalance` at Y. | L2,L3 | el-balance |

### Decision branches explicitly covered
EL-sufficient vs. fill-loop × forced-validators × Gloas vs. pre-fork churn × sweep with/without
partials/builder withdrawals × WeightsNotUpdated × VEBO paused × encode ordering.

> **Out of scope for this iteration (flagged for the next):** proposer-duties v2 endpoint
> compatibility (performance collector / EIP-7917) — Scenario E in the manual plan. It belongs to the
> sidecar, not accounting/ejector; add as `PC-0x` once those two modules are green.

---

## 11. Phased rollout

| Milestone | Deliverable | Layer | Exit criterion |
|---|---|---|---|
| **M0 — Reality gate** | `feat/gloas-devnet` runs accounting + ejector one-shot on the ePBS devnet without crashing | L3 | A valid report is computed (no `execution_payload` crash) |
| **M1 — Cassette + replay** | Cassette record mode; replay `cc`/`kac`/EL clients; `@pytest.mark.scenario` marker | L1 infra | One cassette recorded from M0; one golden test green |
| **M2 — Accounting L1** | AC-00…AC-07, AC-09, AC-11 as report-golden tests + invariant library | L1 | All green in default CI job |
| **M3 — Ejector L1** | EJ-00…EJ-09 as report-golden tests | L1 | All green in default CI job |
| **M4 — Fork L2 content** | Extend `tests/fork/` to assert report content + accept-on-chain or policy-gated non-submission; feed cassettes as CL | L2 | AC-01/02/03/04/05/08, EJ-01/02/03/04 green on fork CI |
| **M5 — Devnet acceptance + runbook gen** | pytest acceptance suite + assertoor playbooks; runbook generated from scenarios | L3 | Full A–E manual plan reproduced automatically; HTML dashboard published |
| **M6 — Generalize** | Template the Scenario/cassette layers for CSM/CM | all | CSM smoke scenario green |

### 11.1 Current implementation status

- The `scenario` pytest marker and offline `tests/scenarios/` suite are active.
- Current verification baseline: `poetry run pytest -q tests/scenarios` reports **26 passed**;
  `poetry run pytest -q tests/fork/test_glamsterdam_layer2.py` reports **7 passed, 7 skipped**
  (the skips are module-incompatible cassette/test combinations).
- Checked-in Layer-2 cassette inventory: accounting AC-01, synthetic AC-02, AC-03, AC-04, AC-05,
  AC-10, plus real-devnet Ejector `EJ-02-devnet-empty-36255`. The corresponding EL archive is
  under `tests/el-archives/`; once warmed, these tests run without the source devnet.
- Accounting AC-00–AC-03 and the one-item branch of AC-07 build exact golden reports; ejector
  report encoding, the EJ-02 devnet cassette, the EJ-04 sweep-manipulation case, and the EJ-09
  builder-exclusion case are active.
- EJ-09 (`tests/scenarios/test_ejector_scenarios.py::TestEjectorBuilderEntriesExcluded`) is a Layer-1
  test only, by design: it exercises the real `compute_lido_validators` / `get_active_lido_validators`
  seam with an EIP-7732 builder-registry entry (index `2^40 + 7`, `0x03` credentials) present in the CL
  validator list and asserts, against an independently derived set, that the pubkey-keyed KAPI filter
  drops it. No Layer-2 variant exists because the exclusion is a property of the key filter, not of any
  on-chain submission path. EJ-05 is intentionally absent — see its §10 row.
- A versioned logical-call cassette loader, recorder, compressed response support, and typed CL/KAPI
  adapters exist. The real Glamsterdam AC-01 cassette at ref slot 36255 includes the prior-report and
  intraframe checkpoints required by bunker detection, including an explicitly recorded missed slot.
- Layer 2 AC-01 runs the full accounting calculation against cassette CL/KAPI data and forked deployed
  EL contracts. It compares all 19 report fields to a golden tuple, reaches quorum through a fresh
  two-member HashConsensus, submits to the deployed AccountingOracle, proves the sanity-check path
  accepted the report, and decodes the transaction calldata to verify the submitted tuple exactly.
- Layer 2 AC-02 is a provenance-locked synthetic overlay on AC-01: the child points to the previous
  confirmed EL payload, two real Lido validator balances are reduced by 1 and 2 ETH, and matching
  expected withdrawals are inserted. The full cycle proves the 3 ETH add-back restores total and
  per-module balances before HashConsensus and AccountingOracle accept the exact golden report.
- Layer 2 AC-03 is a provenance-locked overlay on AC-02. It adds a 5 ETH withdrawal with builder
  index `2^40 + 7`; replay preserves the flagged index, while accounting excludes it from the Lido
  correction. The resulting report remains byte-for-byte equal to AC-02 and is accepted on-chain.
- Layer 2 AC-04 replaces AC-02's small pair with 16 one-ETH Lido withdrawals spanning three staking
  modules and applies matching raw balance reductions. The full correction restores the baseline
  total and module balances, bunker mode remains false, and the exact report is accepted on-chain.
- Layer 2 AC-05 chains from AC-04 and removes only the withdrawal evidence. The exact 16 ETH raw loss
  is therefore reported, the simulated CL rebase is negative, `is_bunker=True`, the bunker safe
  border is earlier than the turbo border, and the daemon submission gate leaves the AccountingOracle
  at its prior ref slot when bunker reporting is disabled. This devnet has no queued withdrawals, so
  the test compares border epochs directly. Its deployed `OracleDaemonConfig` is also missing
  `FINALIZATION_MAX_NEGATIVE_REBASE_EPOCH_SHIFT`; the border-only assertion injects the deployment
  metadata value 1350 while report calculation and gating stay on archived contract state.
- Layer 2 AC-10 replays ref slot 25503 followed by three missed slots, resolves the first real child
  at 25507, and submits its independently pinned 19-field report through the same on-chain path.
- Layer 2 EJ-02 records devnet slot 36255 with no withdrawal demand, builds the exact empty VEBO
  report `(5, 36255, 0, 2, b'')`, reaches quorum through a fresh two-member HashConsensus, submits
  to the deployed ValidatorsExitBusOracle, and verifies the decoded calldata and processing state.
  Its EL archive was warmed online once; the normal test is fully offline. Because the public RPC
  rejects the broad historical ranges used by reward prediction and exit-event lookup, EJ-02 mocks
  only those two auxiliary lookups; CL state, contract calls, encoding, consensus, and submission
  remain real.
- Remaining M4 coverage needs recorded or explicitly synthetic inputs for AC-08 and EJ-01/03/04.
  Layer 3 is not yet implemented by this framework.

### 11.2 Next session hand-off

**Where things stand (2026-07-23).** Synthetic scenarios done: accounting AC-02–AC-05, ejector EJ-04
(sweep manipulation) and EJ-09 (builder exclusion, L1). EJ-05 dropped by design. Flag-check scenarios
EJ-08 and AC-06(a–c) are covered by pre-existing L1 unit tests (annotated in §9/§10). The
`docs/glamsterdam-devnet-scenario-setup.md` runbook is written and the record→scan pipeline is verified
working against the **current** devnet `glamsterdam-kurtosis-7` (signer holds ~20k stETH, buffer
~19,383 ETH, `GLOAS_FORK_EPOCH=3`).

**Preservation rules (do not break these):**
- Preserve existing cassettes / EL archives; do not regenerate synthetic overlays (AC-02–AC-05) without
  rebasing their manifest hashes.
- Do not hand-write CL data for *normal* scenarios — reach the state on the devnet, wait for a finalized
  frame, `scan_oracle_scenarios`, then `record_oracle_scenario_cassette`.

**Prioritized next tasks (fastest / least-extreme first):**

1. **EJ-06 — the one achievable non-empty ejector report (no keys, no deposits, no buffer drain).**
   `get_remaining_forced_validators` fires when a node operator is in FORCE target-limit mode
   (`force_exit_to`, `exit_order_iterator.py:168`). On the devnet: `sr set-validators-limit 1 <no-id>
   <target < active_count> --hard-limit` (mode 2 = FORCE) on module 1 (has ~10 active Lido validators),
   record the ejector frame, then **`sr unset-validators-limit 1 <no-id>` to revert**. Nothing actually
   exits (we only record). This gives real selection + byte-exact `data` encoding/sorting coverage that
   EJ-01 would, without EJ-01's cost. Assert the forced validators are appended regardless of demand.
2. **AC-11 — cross-module consistency (zero devnet writes).** From one baseline frame (fresh or existing
   cassette), assert accounting + ejector observe the same `ref_slot`, EL anchor Y, and `pending_deposits`.
3. **Generalize `scripts/refresh_oracle_scenario.py`** — currently assumes `--module accounting`; add
   `--module ejector` so it is the single regeneration command (the recorder already supports both).
4. **AC-08 — deposit reconciliation (moderate).** Needs a `lido deposit` (consumes *existing* vetted
   depositable keys — check `sr module-summary 1` first; does NOT need activation, only a pending
   deposit). Snapshot the accounting frame whose ref-slot payload contains the deposit.
5. **Deferred — EJ-01 / EJ-03 (extreme; needs coordination).** A non-empty *demand-driven* report needs
   `unfinalized_steth > buffered_ether` (~19.4k stETH) or the buffer drained by depositing into new
   validators (vetted keys + activation → cross-team, cannot be done solo at night). Do NOT attempt with
   a modest `wq` request — the buffer reserves against it and the report is (correctly) empty. See
   runbook §1 and §4.
6. **Layer 3** acceptance (real devnet daemon run + assertoor) remains unimplemented (M5).

**Known nit:** the lido-cli `.env` `KEYS_API_PROVIDER` points at the consensus host (copy-paste slip);
fix before running any lido-cli command that reads KAPI. The recorder's own net-config is correct.

---

## 12. Risks, assumptions, open questions

**Key decision for review (§0):** Is a **recorded-cassette corpus** acceptable as the CI source of
truth for CL/EL inputs? My recommendation is **yes** — it is the only way to get a fast, deterministic
inner loop for CL-shape-dependent behavior — with the guardrail that (a) cassettes are always recorded
from a real devnet (never hand-written), (b) each cassette records the `/eth/v1/config/spec` it was
taken against so a spec bump invalidates it loudly, and (c) Layer 3 periodically re-records. The
alternative (live CL for every integration test) is simpler to reason about but reintroduces exactly
the devnet-coupling and slowness the spec wants to eliminate.

**Risks:**
- *Cassette drift.* Mitigated by spec-pinning + Layer-3 re-record + failing loudly on unknown fields.
- *ePBS devnet instability* (doc notes Lighthouse stalls at the Gloas boundary; Prysm `-sync` works).
  M0 must pin a known-good client set.
- *Anvil is EL-only.* Accepted and designed around — CL always comes from cassette or real node.
- *On-chain simulation dependency* (`accounting.simulate_oracle_report`) means AC finalization/share-
  rate assertions are only fully meaningful at L2/L3; at L1 we assert structure + fake the simulation
  result via the existing `ReportSimulationResultsFactory`.

**Assumptions to confirm before trusting results** (carried from the manual plan): the CL client's
`/eth/v1/config/spec` announces the `GLOAS_FORK_EPOCH` key the oracle reads; `debug/beacon/states`
exposes `latest_block_hash` + `payload_expected_withdrawals`; post-fork blocks expose
`signed_execution_payload_bid.message.block_hash` and no `execution_payload`. If any differ, fix the
dataclasses in `src/providers/consensus/types.py` and `src/utils/blockstamp.py` **first** — the
cassettes will then be recorded against the corrected shapes.

**Open questions for the team:**
1. Cassette corpus location & size budget — in-repo (`tests/cassettes/`) vs. a fixtures submodule?
2. Do we want L2 fork CI to run on every PR, or nightly (it self-skips today when mixed with others)?
3. Is CSM/CM generalization (M6) in scope for the Glamsterdam release, or a follow-up?
