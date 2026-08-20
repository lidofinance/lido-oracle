# Glamsterdam devnet — scenario setup runbook (deposits/withdrawals → cassettes)

How to drive the live `glamsterdam-kurtosis-7` devnet with **lido-cli** into the states the oracle
test scenarios need, then snapshot each state into a checked-in cassette. Companion to
`docs/oracle-testing-framework-plan.md` (§8 runbook, §9–§10 scenario catalogues).

> ⚠️ Every command marked **WRITE** mutates the shared devnet. Read the calibration values first,
> keep amounts minimal, and coordinate — the devnet is not disposable per-developer.

---

## 0. Environment status (verified 2026-07-23)

lido-cli lives at `~/lido/lido-local-devnet/artifacts/devnet0-srv3-consolidation/lidoCLI` (old devnet
name in the path; its `.env` + `configs/deployed-local-devnet.json` are pointed at the current
devnet). Verified working end-to-end:

| Check | Result |
|---|---|
| Toolchain | node v22.20, `./run.sh <cmd>` (ts-node) runs |
| EL | `eth_chainId = 0x7e7e` (32382), advancing |
| CL | head slot ~38164 (epoch ~1192), finalizing; **`GLOAS_FORK_EPOCH = 3`** → deeply post-fork |
| Fork params | `CHURN_LIMIT_QUOTIENT_GLOAS = 32768` (EIP-8061), 32 slots/epoch @ 12s (epoch = 6.4 min) |
| Config↔chain | locator/AO/VEBO/SR proxies have code; `locator accounting-oracle` → `0x8A28…0811`, `exit-bus-oracle` → `0x2af4…FD49`, `withdrawal-queue` → `0xaDe6…6b01` |
| Keys API | up (appVersion 4.0.1, chainId 32382); module 1 = `curated-onchain-v1`, module 2 present |
| Recorder net-config | `tests/scenarios/networks/glamsterdam-kurtosis-7.json`; its endpoints are environment-variable names, so export `ORACLE_SCENARIO_KURTOSIS_7_{EXECUTION,CONSENSUS,KEYS_API}_URI` with the live devnet URLs |

**Live calibration (starting point):**

| Value | Reading |
|---|---|
| `lido total-supply` | 20,023.5 stETH |
| `lido buffered-ether` | **19,383.3 ETH** (almost everything is buffered, not on the CL) |
| `lido depositable-ether` | 19,383.3 ETH |
| `wq unfinalized-steth` | **0.0** (no withdrawal demand → ejector currently reports empty; this is the EJ-02 baseline) |
| `wq last-request` / `last-finalized` | 0 / 0 |
| `wq is-paused` | false |

**One nit to fix in the CLI `.env`:** `KEYS_API_PROVIDER` currently points at the *consensus* host
(`…-consensus…`), a copy-paste slip. It doesn't affect deposits/withdrawals, but any lido-cli command
that reads KAPI will misbehave. The recorder's own net-config uses the correct `…-keys-api…` host, so
cassette recording is unaffected.

---

## 0.1. Using lido-cli against the devnet

lido-cli is a TypeScript tool (`commander` + `ethers` v6) invoked via `./run.sh <group> <cmd> [args]`
(that wraps `npx ts-node ./index`). It is **not** the Rust/Go `lido-cli` binary — same role, different
implementation. Everything runs from the CLI directory.

```bash
cd ~/lido/lido-local-devnet/artifacts/devnet0-srv3-consolidation/lidoCLI
yarn                       # one-time: install deps (node_modules already present here)
./run.sh --help            # list command groups
./run.sh <group> --help    # list a group's subcommands, e.g. `./run.sh wq --help`
```

**How it resolves the network** (`configs/`, `providers/`, `.env`):
- `.env` `EL_API_PROVIDER` / `CL_API_PROVIDER` → JSON-RPC + beacon endpoints (already set to this devnet).
- `.env` `DEPLOYED=deployed-local-devnet.json` → the CLI loads `configs/deployed-local-devnet.json`
  merged with `configs/extra-deployed-local-devnet.json` for all contract addresses. To repoint at a
  new devnet, replace those two files (or change `DEPLOYED`) — do **not** hand-edit addresses.
- `.env` `PRIVATE_KEY` (or `ACCOUNT_FILE` + `ACCOUNT_FILE_PASSWORD`) → the signer used for WRITE txs.
- `NODE_TLS_REJECT_UNAUTHORIZED=0` is set because the devnet endpoints use self-signed TLS.

**Verify the CLI is talking to the right chain (READ-only, safe):**
```bash
./run.sh accounts address                # signer address
./run.sh locator accounting-oracle       # must print 0x8A28…0811 (matches deployed config on-chain)
./run.sh locator exit-bus-oracle         # must print 0x2af4…FD49
./run.sh lido total-supply               # sanity: protocol is live (~20,023 stETH)
./run.sh wq unfinalized-steth            # current ejector demand (0 = empty-report baseline)
```
If `locator …` prints the expected addresses and `total-supply` returns a value, the CLI, config, and
signer are correctly wired to this devnet.

**Command groups you will actually use** (full surface via `./run.sh --help`):

| Group | Alias | Use for |
|---|---|---|
| `lido` | `steth` | `submit` (stake→mint stETH), `deposit <n> <mod>` (buffer→validators, needs DSM=EOA), `buffered-ether`, `depositable-ether`, `total-supply` |
| `withdrawal-request` | `wq` | `request`/`requests` (create demand), `unfinalized-steth`, `is-paused`/`pause`/`resume`, `finalization-batches`, `bunker` |
| `execution-layer-requests` | `el-requests` | `wr <pubkey> [amount]` (EIP-7002 partial/full exit), `cr <src> <tgt>` (consolidation) |
| `validators` | — | `voluntary-exit`, `slash-by-attestations` (induces negative rebase for AC-05), `statuses` |
| `exit-bus-oracle` | `vebo` | `pause`/`resume` (EJ-08), consensus/version reads |
| `staking-router` | `sr` | module + node-operator state (check depositable keys before `lido deposit`) |
| `devnet` | — | `replace-dsm-with-eoa <eoa>` (enable `lido deposit`), `setup` |

**Conventions:**
- `--non-interactive` skips prompts (useful for scripting); otherwise WRITE commands prompt to confirm.
- Amounts are decimal ETH/stETH (e.g. `./run.sh lido submit 32`), not wei.
- Nothing here mutates state until you run a WRITE command from §3; all reads above are safe.

---

## 1. Why the balance model dictates the recipe

The ejector emits a non-empty report only when, at the ref slot,
`unfinalized_steth > predictable_el_balance` (`ejector.py::get_validators_to_eject`), where
(`_get_predicted_el_balance`):

```
predictable_el_balance = future_rewards
                       + future_withdrawals            # balances of Lido validators withdrawable by the withdrawal epoch
                       + total_available_balance        # el-rewards-vault + withdrawal-vault + lido.getWithdrawalsReserve()
                       + going_to_withdraw_balance       # already-requested-to-exit validators
                       - deposit_lock
```

`total_available_balance` (`_get_total_el_balance`) = el-vault + withdrawal-vault +
`lido.getWithdrawalsReserve()`. **Verified live: `getWithdrawalsReserve()` reflects buffered ETH
reserved for the withdrawal queue** — it is 0 only because demand is 0. As soon as a `wq` request
creates demand, the 19,383 ETH buffer reserves against it, so `predictable_el_balance ≥ demand` and the
ejector correctly stays empty. This is *correct protocol behavior*: if the buffer covers the queue, no
validator needs to exit.

**Consequence (verified, not assumed):** a non-empty ejector report requires demand that exceeds what
the buffer can cover — i.e. `unfinalized_steth > buffered_ether` (~19,383 ETH today) — **or** the buffer
first drained by depositing into validators. The scan tool encodes exactly this (`unfinalized_steth >
liquid_el`, where `liquid_el` includes `getBufferedEther()`). Both routes are "extreme" on this devnet:
requesting ~19.4k stETH withdrawals, or depositing (which needs vetted keys + activation). **EJ-01/EJ-03
are therefore not cheap-to-reach here** — see §6 and prefer the low-impact scenarios first.

---

## 1b. Least-extreme scenarios (start here)

Ordered by devnet footprint. The first needs **zero writes** and is the right first milestone — it
proves the record→archive→golden pipeline works against *this* devnet before spending any write budget.

Ordered by footprint / value. Note what is **already done** so no effort is wasted there.

| Priority | Scenario | Writes | Needs validators/keys | Notes |
|---|---|---|---|---|
| 1 | **EJ-06** — forced validators (FORCE target-limit) → **non-empty** report | `sr set-validators-limit … --hard-limit` + revert | no | Highest value/effort ratio: real selection + `data` encoding coverage with **no** deposits/keys/buffer-drain. Recipe in §4. |
| 2 | **AC-11** — cross-module consistency | none | no | Pure read from a baseline frame; same `ref_slot`/anchor/`pending_deposits` across modules. |
| — | EJ-08, AC-06(a–c) | — | no | **Already covered** by existing L1 unit tests (see framework-plan §9/§10). Nothing to do. |
| — | Fresh AC-01/EJ-02 baseline record | none | no | **Redundant for coverage** — already on L2. Only worth it to re-validate the pipeline on a brand-new devnet. |
| — | EJ-01 / EJ-03 (churn) | heavy | **yes** | Deferred: need buffer drain (deposits + vetted keys + activation → cross-team) or ~19.4k stETH demand. See §4. |
| — | AC-08 (deposit reconcile) | `lido deposit` | uses existing keys | Moderate: needs vetted depositable keys (`sr module-summary 1`); no activation wait. |

**Recommended first:** EJ-06 (the only non-extreme route to a non-empty ejector report), then AC-11.

---

## 2. Preflight (READ-only)

```bash
cd ~/lido/lido-local-devnet/artifacts/devnet0-srv3-consolidation/lidoCLI
./run.sh lido is-stopped            # protocol resumed?
./run.sh lido is-staking-paused     # staking open?
./run.sh accounts                   # signer address + balance (must hold ETH to submit/pay fees)
./run.sh sr module-summary 1        # curated module: depositable keys available for `lido deposit`?
./run.sh validators statuses        # how many active Lido validators exist right now
```

Deposits via `lido deposit` require **DSM set to an EOA**. If not already done:

```bash
./run.sh devnet replace-dsm-with-eoa <your-eoa>     # WRITE — one-time devnet setup
```

If the curated module has **no depositable keys**, that is a separate (heavier) prerequisite: generate
deposit data and add/vet keys through the node-operator registry before any `lido deposit` will work.
Check `sr module 1` output first; do not assume keys exist.

---

## 3. Building blocks (verified command surface)

### 3a. Deposit pipeline (buffer → active validators)
```bash
./run.sh lido submit <ETH>            # WRITE — stake ETH, mints stETH into the buffer (only if more buffer is wanted)
./run.sh lido deposit <n> 1           # WRITE — deposit n×32 ETH from buffer to module 1 (needs DSM=EOA + n depositable keys)
./run.sh validators statuses          # READ — watch the new validators appear/activate on the CL
```
New validators must **activate** on the CL (activation queue + churn) before they are selection
candidates. At 6.4 min/epoch this is minutes-to-hours depending on queue depth — plan for the wait.

### 3b. Withdrawal-demand pipeline (drives the ejector)
```bash
./run.sh wq request <stETH>              # WRITE — one withdrawal request
./run.sh wq requests <stETH> <count>     # WRITE — many requests (to build large demand)
./run.sh wq unfinalized-steth            # READ — this IS the ejector's `to_withdraw_amount`
```

### 3c. EIP-7002 pipeline (partials, forced exits)
```bash
./run.sh el-requests wr <pubkey> <amount>   # WRITE — partial withdrawal (amount>0) → pending_partial_withdrawals
./run.sh el-requests wr <pubkey> 0          # WRITE — full exit request (amount=0)
./run.sh el-requests cr <src-pubkey> <tgt-pubkey>   # WRITE — consolidation request
```

### 3d. Contract-state toggles (no deposits/withdrawals needed)
```bash
./run.sh wq pause <duration> / ./run.sh wq resume     # WRITE — AC-06(a): finalization batches empty when paused
./run.sh vebo pause <duration> / ./run.sh vebo resume # WRITE — EJ-08: is_reporting_allowed=False → no report
```

### 3e. Slashing (makes AC-05 reproducible for real, not just synthetic)
```bash
./run.sh validators slash-by-attestations <mnemonic> <index> <slot>   # WRITE — induces a real negative rebase
./run.sh validators voluntary-exit <mnemonic> <index>                 # WRITE — CL voluntary exit
```

---

## 4. Per-scenario recipes

For every recipe: after reaching the state, **calibrate with an oracle dry-run** before snapshotting
(see §5). Amounts below are shapes, not final numbers — read the dry-run's `predictable_el_balance`
and set `wq` demand to exceed it by a margin.

### EJ-01 — non-empty exit report (`demand > predictable EL balance`) — **EXTREME on this devnet**
The ejector only ejects once demand exceeds the reservable buffer (~19,383 ETH). Two routes, both heavy:
- **Drain the buffer:** `lido deposit <n> 1` to move buffer into validators (needs vetted keys +
  activation wait — cross-team dependency), then a modest `wq` request tips the balance.
- **Overwhelm the buffer:** `wq requests <stETH> <count>` totalling **> `buffered-ether`** (~19.4k stETH).
  Near-total drain of Lido stETH on a shared devnet — coordinate first.

Do **not** attempt EJ-01 with a modest request expecting a non-empty report — the buffer absorbs it and
the report is (correctly) empty. Confirm the threshold with the scan tool's `liquid_el_wei` first.
Expected once triggered: `requests_count > 0`, `data` byte-exact and sorted by `(module_id, no_id,
validator.index)`.

### EJ-03 — EIP-8061 churn (post-fork)
Already post-fork, so the churn path is live. Reuse EJ-01's demand state but make the validator set
large enough that `total_active_balance` is non-trivial (deposit more in step 1). Assert the predicted
`withdrawable_epoch` uses `get_exit_churn_limit` (uncapped, quotient 32768) and that the ejector
selects **≥** what the pre-fork capped formula would. Same snapshot mechanics.

### EJ-06 — forced validators appended regardless of demand — **the non-extreme non-empty report**
Verified trigger: `get_remaining_forced_validators` fires when a node operator is in **FORCE**
target-limit mode (`exit_order_iterator.py:168`, `force_exit_to = target_validators_count` when
`is_target_limit_active == FORCE`). This needs no deposits, no keys, and no buffer drain — it reuses
existing active Lido validators, and with demand at 0 the forced entries are the *only* ones, so the
report exercises real selection + byte-exact `data` sorting.

```bash
# module 1 has ~10 active Lido validators; pick a node-operator id with active validators
./run.sh sr module-summary 1                          # READ — find a NO and its active count
./run.sh sr set-validators-limit 1 <no-id> <target> --hard-limit   # WRITE — FORCE mode (mode 2), target < active
# ... wait for a finalized ejector frame, then record the cassette (§5) ...
./run.sh sr unset-validators-limit 1 <no-id>          # WRITE — REVERT (mode 0). Always run this after.
```
Nothing actually exits — recording only reads the computed report. Expected: `requests_count ==
(active − target)` for that operator, entries sorted by `(module_id, no_id, validator.index)`, present
even though `unfinalized-steth == 0`.

### AC-08 — deposit reconciliation (deposit lands in ref-slot's own payload)
1. `lido deposit <n> 1` (WRITE).
2. Snapshot the **accounting** frame whose ref slot's own payload contains that deposit. Expected:
   `postCLPendingBalance` reconciles with `Lido.sol`'s counter, no `_checkCLPendingBalance…` revert.

### Pure toggles (no deposits/withdrawals) — for completeness
EJ-08 (`vebo pause`), AC-06(a) (`wq pause`), AC-05 (`validators slash-by-attestations`).

---

## 5. Snapshot & verify (turn a live state into a cassette)

All recorder commands run from the **oracle repo** (`~/lido/lido-oracle`) with the net-config that is
already aligned to this devnet.

1. **Find a ref slot showing the condition** (scan recent frames):
   ```bash
   poetry run python -m scripts.scan_oracle_scenarios \
       --network-config tests/scenarios/networks/glamsterdam-kurtosis-7.json \
       --frames 24 --include-empty
   ```
2. **Record the cassette + EL archive** for the chosen finalized ref slot:
   ```bash
   poetry run python -m scripts.record_oracle_scenario_cassette \
       --network-config tests/scenarios/networks/glamsterdam-kurtosis-7.json \
       --module ejector --scenario-id EJ-01-devnet-demand-<slot> \
       --ref-slot <slot> \
       --output tests/cassettes/glamsterdam-kurtosis-7/EJ-01-devnet-demand-<slot>
   ```
   Add `--historical-ref-slot <N>` for the prior-frame lookbacks the module needs (e.g. bunker
   detection, reward prediction). `refresh_oracle_scenario.py` is the combined record+archive wrapper;
   note it currently assumes `--module accounting` and must be generalized before use for ejector
   (tracked in the framework plan §11.2).
3. **Pin a golden and verify offline:**
   ```bash
   poetry run pytest -q tests/scenarios -k EJ-01     # Layer 1
   poetry run pytest -q tests/fork/test_glamsterdam_layer2.py -k EJ-01   # Layer 2 (once wired)
   ```
   The ref slot must be **finalized** before recording; snapshotting a non-final slot yields a cassette
   that a re-org can invalidate.

---

## 6. Timing & gotchas

- **Activation/exit latency.** Deposited validators must activate before they can be ejected;
  ejected/exited validators need exit-epoch + withdrawability delay to actually leave. For EJ-01/EJ-03
  we only need the ejector to *compute* a selection at a ref slot, so wait for **activation** only —
  not for exits.
- **Buffer dominance.** Because the buffer isn't in `predictable_el_balance`, small demand forces
  ejection but the accounting oracle will still finalize the queue from the buffer — the two modules
  see the same frame differently; don't cross-wire expectations.
- **Frame length.** Read the ejector frame from its HashConsensus (`vebo-consensus`) and
  `get_ejector_last_processing_ref_slot` rather than assuming the 45-epoch mainnet frame; devnets use
  short frames.
- **Shared devnet.** Withdrawal requests and pauses affect everyone. Prefer additive, minimal states;
  resume anything you pause.
- **Cassette faithfulness.** Record from real finalized state only (framework principle §3.5). The
  synthetic overlays (AC-02…AC-05, EJ-04/EJ-09) stay hand-authored; these devnet recipes are for the
  *normal* scenarios (EJ-01/EJ-03/EJ-06, AC-06/07/08/09).
