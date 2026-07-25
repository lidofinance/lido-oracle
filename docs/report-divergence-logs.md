# Diagnosing a report divergence from logs

When oracle members submit different report hashes for the same reference slot, they
disagree about an *input*, not about arithmetic. The three inputs large enough to hide a
disagreement are the beacon state (~900 MB), the Keys API used-key set (~485k keys,
~47 MB) and the pending deposit queue. None can be logged as-is, so the oracle logs
fingerprints of them: two members' log files are then enough to say which layer diverged,
and usually to name the exact key or deposit responsible, without either operator sharing
any data.

Only one set carries a full recovery sketch — the pending validators the report is summed
from — because it is the one that cannot be reconstructed later. A past beacon state needs
an archive node nobody kept, but its `state_root` already proves whether two members read
the same one; and a Keys API difference that can move a report is a persistent bookkeeping
error, so those two instances still disagree today and can simply be diffed live.

## The fingerprint fields

Every fingerprinted set is logged as two lines: `<subject> fingerprint.` with a small
summary, and — for the one set that needs entry recovery — `<subject> sketch.`, emitted in
numbered parts so log shipping can drop it independently.

| Line          | Field           | Use                                                     |
|---------------|-----------------|----------------------------------------------------------|
| `fingerprint.`| `count`         | Did the two members even see the same number of entries?   |
| `fingerprint.`| `digest`        | keccak over the sorted set — equal digests mean identical sets. |
| `fingerprint.`| `xor`           | All entries XOR-ed together. If the sets differ by exactly one entry, XOR-ing the two members' values gives that entry, by hand, with no tooling. |
| `sketch.`     | `iblt`          | **Recovers the complete difference — every entry either side is missing, and which side is missing it.** |
| `sketch.`     | `bucket_counts` | Entries per 1/256 of the keyspace; a coarse fallback if the sketch cannot decode. |

### Recovering the differing entries

Pull *every part* of the sketch for the same reference slot from each member:

```bash
grep '"msg": "Pending Lido validators sketch."' member-a.log > a.json
grep '"msg": "Pending Lido validators sketch."' member-b.log > b.json

python3 scripts/reconcile_fingerprints.py a.json b.json \
    --left-name 0xa2432f5b --right-name 0xafd9bcb7
```

The sketch is split across ~7 lines of ~10 KB, each carrying `part` and `parts`. Docker's
`json-file` driver and containerd both cut a log message at 16 KB and leave reassembly to
whatever collector you run, so the parts are numbered here instead — a missing one is an
error from the script, not a sketch that quietly decodes to nothing.

```
only in 0xa2432f5b: 0x4587b0bd9c58b865b10b221b730b719d088c08f6718f4bddf62dd254674b4b5c…
only in 0xa2432f5b: 0x72e660351808d21657cb80dd80734d41da767dde4a08240c6fcdb35e5c912939…

Recovered the complete difference: 2 entries.
```

No key data changes hands: each member's own log line is a sketch of its own inputs, and
the difference falls out of the pair. The sketch is an [invertible Bloom lookup
table](https://arxiv.org/abs/1101.2245) — each entry is XOR-ed into 4 of 512 cells, so
subtracting two sketches leaves cells holding a single differing entry, which peel off and
free their neighbours in turn.

**Capacity is on the difference, not the set.** 512 cells resolve up to ~380 *differing*
entries regardless of how large the sets are — a 485k used-key set or a 40k deposit queue
sketches and decodes just the same. Past ~380 differences an IBLT decodes *nothing* rather
than degrading, so the script says so explicitly and exits non-zero; treat any entries it
printed as real but incomplete.

**When thousands differ,** entry-by-entry recovery is the wrong tool anyway — sizing a
sketch for that would cost megabytes per log line, and a divergence that big does not need
naming key by key, only locating. Use instead:

- `Used keys vs deposited validators per node operator.` — fires by itself when an
  operator's used keys fall short of the Staking Router's count, naming that operator.
- `by_module` on `Used Lido keys fingerprint.` — the same at module granularity.
- `bucket_counts` on part 1 of a `sketch.` line — 256 counts over the keyspace, showing
  whether the difference is concentrated or spread.

If you have only the `fingerprint.` line and exactly one entry differs (`count` differs by
1), you do not need the script at all:

```bash
# 48-byte pubkeys — Used Lido keys, Pending Lido keys, Pending Lido validators, CL validators
python3 -c "print('0x%096x' % (int('<xor_a>', 16) ^ int('<xor_b>', 16)))"

# 96-byte deposit records — Pending deposits: pubkey|wc|amount|slot
python3 -c "print('0x%0192x' % (int('<xor_a>', 16) ^ int('<xor_b>', 16)))"
```

Deposit entries omit the 96-byte signature, which identifies nothing the other four fields
do not. A deposit rejected *because* of its signature is logged in full separately, and
`pending_deposits_queue_digest` covers the signature, so a signature-only divergence is
still detected.

## What to compare, in order

Work down the pipeline; the first line whose values differ names the layer at fault.

| `msg`                                                  | Pins                                                                |
|--------------------------------------------------------|---------------------------------------------------------------------|
| `BLS deposit signature self-check.`                      | Startup. Backend path, deposit domain, signing root, and the verdicts on a known-good and a tampered vector. Different `signing_root` ⇒ SSZ/domain difference; same root and different verdict ⇒ curve library difference. |
| `Beacon state summary.`                                  | `state_root`, validator count, balance sum, pending deposit count and total, and the order-sensitive `pending_deposits_queue_digest`. |
| `Pending deposits fingerprint.`                          | The CL deposit queue as a set. Differs ⇒ the consensus layer, not the oracle. |
| `CL validators fingerprint.`                             | The validator registry.                                              |
| `Keys API response snapshot.`                            | Per request: the `elBlockSnapshot` the answer came from, including `lastChangedBlockHash`. Same value on both sides ⇒ both Keys APIs consumed the same on-chain key updates. |
| `Used Lido keys fingerprint.`                            | The used-key set, plus per-module counts. **This is where the 2026-07-25 split lived.** |
| `Get pending deposits and not-yet-indexed lido keys.`    | `lido_wc_list` and `genesis_fork_version` — the two constants the deposit filter depends on. |
| `Pending Lido keys fingerprint.`                         | Keys with no validator record yet: the left side of the intersection. |
| `Collect valid pending deposits.`                        | How many signatures were verified and how many were rejected, with the rejected and frontrun pubkeys listed. |
| `Get pending lido validators.`                           | `total_amount_gwei` — half of what `clPendingBalanceGwei` is built from. |
| `Pending top-ups fingerprint.`                           | The other half: deposits queued against already-active Lido validators. |
| `Pending Lido validators fingerprint.`                   | The final selected set.                                              |

## Worked example: the pending balance differs

Two members, same reference slot, different `clPendingBalanceGwei`. Work down; the first
line whose values differ names the layer, and only then do you decode anything.

### 0. Which half?

```
Calculate CL pending validators balance.   value  ← the number in the report
Calculate new pending validators balance.  value  ← half A: not-yet-activated keys
Calculate pending top-ups balance.         value  ← half B: top-ups to active validators
```

Half A → steps 1–4. Half B → step 5.

### 1. Rule the consensus layer in or out

```
Beacon state summary.          state_root, pending_deposits, pending_deposits_queue_digest
Pending deposits fingerprint.  count, digest, xor
```

- `state_root` differs → the members read *different states*. Not a data bug; check the
  reference slot and for a reorg.
- `state_root` equal, `digest` equal → **the deposit queue is provably identical.** The
  state is fetched by state root, which commits to the whole `BeaconState`. Go to step 2.
- `state_root` equal, `digest` differs → a consensus client returned bytes inconsistent
  with the root it was handed. That is a client bug; escalate with both digests. If `count`
  differs by exactly one, `xor` names the deposit.

### 2. Rule the Keys API in or out

```
Keys API response snapshot.    el_block_snapshot{blockNumber, blockHash, lastChangedBlockHash}
Used Lido keys fingerprint.    count, digest, xor, by_module
```

- Equal `lastChangedBlockHash` → both instances consumed the same on-chain key updates, so
  a difference below is the instance's own bookkeeping, not a different view of the chain.
- `count` differs → one instance is short; `by_module` says which module.
- `digest` differs with equal counts → same size, different membership.

Then recover the keys — this is the step the whole scheme exists for:

`xor` names the key outright when exactly one differs, which is the shape observed so far:

```bash
python3 -c "print('0x%096x' % (int('<xor_a>', 16) ^ int('<xor_b>', 16)))"
```

For more than one, there is no sketch on this set by design — unlike a past beacon state, a
Keys API difference that can move a report is a persistent bookkeeping error, so both
instances still disagree today. Diff them live with
`scripts/ao_report_debug/keys_digest.py`, or run its `--selfcheck` to find a short instance
with no second party at all.

Either way you end with a pubkey. `GET /v1/keys/<pubkey>` against both instances: one has it
`used: true`, the other does not, and the response names the module and operator.

### 3. Both match? Then it is the filter

```
Get pending deposits and not-yet-indexed lido keys.  lido_wc_list, genesis_fork_version
Collect valid pending deposits.                      signatures_verified,
                                                     invalid_signature_deposits,
                                                     invalid_signature_pubkeys,
                                                     invalid_keys, frontrun_pubkeys
BLS deposit signature self-check.                    signing_root, valid_accepted
```

- `lido_wc_list` or `genesis_fork_version` differ → a configuration or contract difference,
  not a data one.
- `invalid_signature_deposits` differ → the BLS backends disagree. The listed pubkeys, plus
  the full per-deposit `Ignoring key. Invalid deposit signature` warnings, give the exact
  tuples to re-verify against the other library.
- `signing_root` differs in the startup self-check → the difference is SSZ or domain
  computation, *not* the curve library. Same root, different `valid_accepted` → the reverse.

### 4. The answer

```
Get pending lido validators.     value, total_amount_gwei
Pending Lido validators sketch.  iblt
```

Reconcile the two sketches as in step 2 for the exact keys behind the balance difference.

### 5. Half B — top-ups

```
Calculate pending top-ups balance.  value, validators_with_topups
Pending top-ups fingerprint.        count, digest, xor
```

`xor` names a single differing top-up outright. For more than one there is no sketch here
by design: this set is `CL deposit queue ∩ used keys ∩ CL validator registry`, and all
three are pinned above — so steps 1 and 2 already identify the key responsible.

## Warnings that name a culprit without a second member

These fire on one member's own data, so they do not need anybody to compare against.

- **`Used keys vs deposited validators at the Keys API block.`** — every deposited Lido key
  must be in the used set, so `len(used keys) == depositedValidators` must hold *at the
  Keys API's own block*. `_kapi_sanity_check` only asserts `>=` against the reference
  block, which a stale key can hide: the Keys API is allowed to run ahead, and keys
  deposited in that gap make up the shortfall. Evaluated at the Keys API's block the
  identity is exact, and a stale key shows up as `deficit: 1`.
- **`Used keys vs deposited validators per node operator.`** — the same identity against the
  Staking Router's `totalDepositedValidators`, per operator. A `shortfalls` entry names the
  operator whose key went missing.
- **`Keys API used-key self-consistency.`** — for each operator, `count(key rows with
  used=true)` must equal the operator row's `usedSigningKeys`. A shortfall means the Keys
  API knows the operator deposited N keys but has flagged only N-1 used. Only emitted on
  the per-module endpoint, so the CSM and CM oracles see it, the accounting oracle does not.
- **`Ignoring key. Invalid deposit signature`** / **`Ignoring key. Possible front run attack`** —
  a deposit excluded from the pending balance, logged with the full record so it can be
  re-verified against another BLS backend later.

All of the above are diagnostics: they log and continue, and never fail a report.

## Cost

Fingerprinting the mainnet used-key set (~485k entries) takes ~2.6 s, once per report
cycle, against a state fetch measured in minutes. Six summary lines of 250–400 bytes, plus
the one sketch — ~7 parts of ~10 KB — for about 65 KB a cycle.

Summary lines are deliberately small so they can be grepped and shipped; everything bulk is
on its own line and can be dropped by log shipping without losing the ability to *detect* a
divergence, only the ability to resolve one from the logs alone.
