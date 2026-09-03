# Oracle report scenarios

Report-level scenario tests for the oracle modules. This is the first, offline layer (**Layer 1**)
of the testing framework described in [`docs/oracle-testing-framework-plan.md`](../../docs/oracle-testing-framework-plan.md).

A scenario builds the **full** `ReportData` tuple end-to-end through the module's `build_report`
from controlled inputs, then asserts two things:

1. an **exact golden tuple** (regression guard), and
2. the shared **correctness invariants** in [`invariants.py`](./invariants.py) (class-of-bug guard —
   e.g. `requests_count` matches the packed payload, entries are sorted and duplicate-free).

Layer 1 is fully offline: `@pytest.mark.unit`, network blocked. Inputs are injected at the module's
data-collection seam (`get_validators_to_eject` for the ejector; `_calculate_report` sub-methods for
accounting) so each scenario maps deterministically to one report.

The cassette foundation in [`cassette.py`](./cassette.py) defines the versioned on-disk format for
recorded CL, EL, and Keys API calls. It rejects stale schema/spec versions and missing calls rather
than falling back to the network. Large beacon states are stored as compressed JSON. The first real
Glamsterdam cassette is checked in under `tests/cassettes/glamsterdam-kurtosis-7/` and its typed
replay adapters exercise the production blockstamp parser without network access.

Rare or adversarial states use **synthetic overlays** rather than copied response blobs. An overlay
references a recorded base cassette, pins the SHA-256 of its manifest, and lists only the JSON-pointer
replacements that define the scenario. `Cassette.load()` applies those replacements in memory and
fails if the base recording changed, the target call/path is absent, or the overlay escapes the
network's cassette directory. The manifest must declare `"origin": "synthetic"` and name its
`base_scenario_id`; this keeps generated protocol states distinguishable from observed devnet data.

The AC-02 overlay is the reference example. It changes the child execution anchor to the previous
confirmed payload, replaces the reference state's expected withdrawals with two Lido validators,
and reduces those validators' raw balances by the same amounts. The Layer-2 assertion independently
checks that the 3 ETH correction is restored in both total and per-module balances.

Prefer a recorded cassette whenever the state can be produced with ordinary `lido-cli` operations,
including deposits and withdrawal requests: perform the operation on the devnet, wait for a suitable
finalized frame, scan it, and record it. Synthetic overlays are reserved for protocol states that are
not reliably producible on demand, such as a withheld payload combined with a builder-index
withdrawal. AC-03 is the reference chained overlay: it extends AC-02 with a `2^40 + 7` builder index
and proves that the builder's 5 ETH is parsed but excluded from the Lido correction.

AC-04 and AC-05 form a controlled synthetic pair. Both reduce the same 16 Lido validator balances
by 1 ETH. AC-04 supplies the matching 16 expected withdrawals, so the accounting report restores
the full balance, remains outside bunker mode, and is accepted on-chain. AC-05 removes only that
withdrawal evidence: the report retains the 16 ETH loss, enters bunker mode, selects an earlier safe
border, and is not submitted when `ALLOW_REPORTING_IN_BUNKER_MODE=False`. The source devnet has no
queued withdrawal requests, so AC-05 compares the safe-border epochs directly rather than claiming
a difference between two empty finalization-batch lists. Its deployed `OracleDaemonConfig` also
omits `FINALIZATION_MAX_NEGATIVE_REBASE_EPOCH_SHIFT`; the Layer-2 test injects the deployment
metadata value (1350) only for that isolated border comparison.

EJ-02 is the first real Ejector Layer-2 cassette. It records the devnet at slot 36255, builds the
empty VEBO report `(5, 36255, 0, 2, b'')`, and submits it through a fresh local HashConsensus
quorum to the deployed ValidatorsExitBusOracle. The public RPC rejects the module's broad
historical log ranges, so the test isolates only those auxiliary event/prediction lookups; CL and
contract state, report encoding, consensus, and submission remain real.

## Current checked-in state

- Layer 1: 24 scenario/cassette tests pass offline.
- Layer 2: AC-01, AC-02, AC-03, AC-04, AC-05, AC-10, and EJ-02 are wired into
  [`tests/fork/test_glamsterdam_layer2.py`](../fork/test_glamsterdam_layer2.py). The complete
  matrix currently reports 7 passed and 7 skipped because each test skips cassettes belonging to
  another oracle module.
- EJ-02 cassette: `tests/cassettes/glamsterdam-kurtosis-7/EJ-02-devnet-empty-36255/` (CL ref slot
  36255, execution anchor block 27374, chain ID 32382).
- EL archive: `tests/el-archives/`; it is a replay cache for the recorded execution anchor, not a
  full blockchain dump. Missing code/storage is added by one online warm-up run.
- The checked-in `refresh_oracle_scenario.py` workflow is currently documented for accounting
  cassettes. EJ-02 was recorded with `record_oracle_scenario_cassette.py --module ejector` and
  warmed by running its Layer-2 test with `UPDATE_ORACLE_EL_ARCHIVES=1`.

## Network descriptors and endpoints

`tests/scenarios/networks/<network>.json` pins the chain id and the deployed contract addresses a
cassette was recorded against. Its `endpoints` hold the **name of an environment variable** rather
than a URL, because devnet endpoints are internal infrastructure:

| Descriptor              | Variables                                                         |
|-------------------------|-------------------------------------------------------------------|
| `glamsterdam-kurtosis-7`| `ORACLE_SCENARIO_KURTOSIS_7_{EXECUTION,CONSENSUS,KEYS_API}_URI`    |
| `glamsterdam-devnet-8`  | `ORACLE_SCENARIO_DEVNET_8_{EXECUTION,CONSENSUS,KEYS_API}_URI`      |

Each endpoint resolves lazily, on first use, so only the commands that genuinely need a live
devnet — `scan`, `record`, `refresh`, and a Layer-2 run with `UPDATE_ORACLE_EL_ARCHIVES=1` — require
these variables. Replaying a checked-in cassette needs none of them, and Layer 2 replaying from a
checked-in EL archive runs with nothing exported. A descriptor may also hold a literal URL, which is
the convenient form for a local devnet.

## Running

```bash
poetry run pytest tests/scenarios/ -v      # or: make test ORACLE_TEST_PATH=tests/scenarios/
poetry run pytest -m scenario -v           # select this layer from the full test tree
```

Record another finalized frame with:

```bash
poetry run python scripts/record_oracle_scenario_cassette.py \
  --network-config tests/scenarios/networks/glamsterdam-kurtosis-7.json \
  --output tests/cassettes/glamsterdam-kurtosis-7/<scenario-and-slot> \
  --scenario-id <scenario-id> --module accounting --ref-slot <finalized-ref-slot>
```

For an accounting scenario that must also run at Layer 2, use the combined refresh command. It
records the CL, Keys API, and execution-block responses, starts an online Anvil fork once to warm
the required contract code/storage, converts that cache into a checked-in EL archive, and runs the
full submission test:

```bash
poetry run python scripts/refresh_oracle_scenario.py \
  --network-config tests/scenarios/networks/<network>.json \
  --scenario-id AC-01-confirmed-payload-<slot> \
  --ref-slot <finalized-ref-slot> \
  --historical-ref-slot <last-accounting-report-ref-slot>
```

The resulting files live under `tests/cassettes/<network>/<scenario-id>/` and
`tests/el-archives/<network>/<execution-block>.{json,block.json}`. After they are created, Layer 2
does not contact the retired devnet:

```bash
poetry run pytest -vv tests/fork/test_glamsterdam_layer2.py
```

To rebuild only the EL archives for already-recorded cassettes, run the Layer-2 test once with
`UPDATE_ORACLE_EL_ARCHIVES=1`. The test accepts `ORACLE_SCENARIO_NETWORK_CONFIG`,
`ORACLE_LAYER2_CASSETTE_PATHS` (colon-separated on Unix), `ORACLE_EL_ARCHIVE_ROOT`, and
`ORACLE_FOUNDRY_RPC_CACHE_ROOT` overrides.

For the existing EJ-02 cassette, the reproducible offline command is:

```bash
env ORACLE_LAYER2_CASSETTE_PATHS=tests/cassettes/glamsterdam-kurtosis-7/EJ-02-devnet-empty-36255 \
  poetry run pytest -q tests/fork/test_glamsterdam_layer2.py -k ejector
```

If its EL archive must be regenerated from a live devnet, add
`UPDATE_ORACLE_EL_ARCHIVES=1` to that command. This requires the devnet endpoints from the
network JSON; after warm-up, the archive and cassette are sufficient for normal test execution.

Refresh intentionally does **not** rewrite expected report tuples. A different network can have
different balances and contract state; the command leaves a failing report diff for review while
still writing the warmed archive during fixture teardown. Synthetic overlays such as AC-02 also
remain explicit, reviewed patches: rebase their manifest hash and semantic patches onto the new
recorded base rather than pretending the adversarial state was observed live.

Scan finalized oracle frames for useful cassette candidates before recording:

```bash
poetry run python scripts/scan_oracle_scenarios.py \
  --network-config tests/scenarios/networks/glamsterdam-kurtosis-7.json \
  --frames 24
```

Add `--include-empty` for diagnostics for every scanned frame, or repeat `--ref-slot <slot>` to
inspect selected frames only. The scanner is read-only and labels candidate conditions; it does not
create protocol state or submit transactions.

## Adding a scenario

1. Pick the module and the decision branch you want to pin (see the catalogue in the plan doc,
   §9 accounting / §10 ejector).
2. Add a test that arranges the injected inputs, calls `build_report`, and asserts the golden tuple.
3. Call the relevant invariant(s) from `invariants.py`. If your scenario needs a new invariant, add
   it there — invariants are the correctness floor and must hold for **every** scenario, so keep them
   scenario-agnostic.

For a synthetic cassette, create a small `manifest.json` plus `overlay.json` beside the recorded
base. Prefer replacing a complete semantic field (for example `payload_expected_withdrawals`) and
make all dependent changes explicit. Never regenerate the golden report from the oracle output;
derive and review it independently.

Scenarios can be added or removed freely; the invariant set does not change with the scenario list.

## Roadmap (next iterations)

- Accounting report-golden scenarios now cover the pre-fork gate, Gloas primary/fallback balance
  handling, builder-index exclusion, one-item extra-data encoding, and the per-module-balance-equality
  invariant. The cassette-backed Layer 2 additionally covers corrected large losses and a true
  negative-rebase bunker gate. Remaining: queued-withdrawal finalization, multi-transaction
  extra-data, and vault reports.
- Extend Layer 2 to additional accounting and ejector scenarios. The current accounting path replays
  cassette CL/KAPI data and a portable archived EL anchor, then executes real HashConsensus and
  AccountingOracle submission without requiring the source devnet.
