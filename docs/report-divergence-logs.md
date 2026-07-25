# Diagnosing a report divergence from logs

When oracle members submit different report hashes for the same reference slot, they
disagree about an *input*, not about arithmetic. The three inputs large enough to hide a
disagreement are the beacon state (~900 MB), the Keys API used-key set (~485k keys,
~47 MB) and the pending deposit queue. None can be logged as-is, so the oracle logs
fingerprints of them: two members' log files are then enough to say which layer diverged,
and usually to name the exact key or deposit responsible, without either operator sharing
any data.

The logs answer *did we read the same data, and where did it stop matching* — cheaply
enough to stay on in every cycle. Naming the individual keys behind a multi-key difference
is left to the live Keys API instances and an archive node, which can still be asked.

## The fingerprint fields

Each fingerprinted set is one log line, `<subject> fingerprint.`, of a few hundred bytes.

| Field | Use |
|---|---|
| `count` | Did the two members see the same number of entries? |
| `digest` | keccak over the sorted set — equal digests mean the sets are identical. |
| `xor` | Every entry XOR-ed together. **If the sets differ by exactly one entry, XOR-ing the two members' values gives that entry.** |

### One entry differs

`count` differs by 1. XOR the two `xor` values and you have the key — no tooling:

```bash
# 48-byte pubkeys
python3 -c "print('0x%096x' % (int('<xor_a>', 16) ^ int('<xor_b>', 16)))"

# 96-byte deposit records — Pending deposits: pubkey|wc|amount|slot
python3 -c "print('0x%0192x' % (int('<xor_a>', 16) ^ int('<xor_b>', 16)))"
```

This is the shape every pending-balance split has taken so far. Check the result with
`GET /v1/keys/<pubkey>` against both Keys API instances: one has it `used: true`, the other
does not, and the response names the module and operator.

### Several entries differ

The XOR is then several entries superimposed and cannot be read back. The logs tell you
*that* the sets differ, which layer, and by how many — not which keys. Deliberately: the
per-slice detail that would answer it costs orders of magnitude more log volume every
cycle, for a case that has not yet occurred.

To name them, go to the live data instead:

- **Keys API** — a difference that can move a report is a persistent bookkeeping error
  rather than a passing view, so the instance is still short today. Find it with
  `scripts/ao_report_debug/keys_digest.py --selfcheck`, which needs one instance and
  nothing else: for every operator, `count(key rows with used=true)` must equal that
  operator's `usedSigningKeys`.
- **Consensus layer** — re-derive from an archive node at the reference slot.

`count`, `by_module` on the used-key set, and the per-operator conservation warnings below
narrow it down first.

## What to compare, in order

Work down the pipeline; the first line whose values differ names the layer at fault.

| `msg`                                                  | Pins                                                                |
|--------------------------------------------------------|---------------------------------------------------------------------|
| `Beacon state summary.`                                  | `state_root`, validator count, balance sum, pending deposit count and total. |
| `Pending deposits fingerprint.`                          | `digest`/`xor` over the deposit queue as a **set**, plus `queue_digest` over it **in order**. Equal set and differing order is itself a divergence: the filter keeps the *first* deposit seen per pubkey, so order decides frontrun. Differs ⇒ the consensus layer, not the oracle. |
| `CL validators fingerprint.`                             | The validator registry.                                              |
| `Keys API response snapshot.`                            | Per request: the `elBlockSnapshot` the answer came from, including `lastChangedBlockHash`. Same value on both sides ⇒ both Keys APIs consumed the same on-chain key updates. |
| `Used Lido keys fingerprint.`                            | The used-key set, plus per-module counts. **This is where the 2026-07-25 split lived.** |
| `Get pending deposits and not-yet-indexed lido keys.`    | `lido_wc_list` and `genesis_fork_version` — the two constants the deposit filter depends on. |
| `Pending Lido keys fingerprint.`                         | Keys with no validator record yet: the left side of the intersection. |
| `Collect valid pending deposits.`                        | How many signatures were verified and how many were rejected. Each rejected deposit is logged in full on its own `Ignoring key.` line. |
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
Beacon state summary.          state_root, pending_deposits, pending_deposits_amount_gwei
Pending deposits fingerprint.  count, digest, xor, queue_digest
```

- `state_root` differs → the members read *different states*. Not a data bug; check the
  reference slot and for a reorg.
- `state_root` equal, `digest` and `queue_digest` equal → **the deposit queue is provably
  identical.** The state is fetched by state root, which commits to the whole `BeaconState`.
  Go to step 2.
- `digest` equal, `queue_digest` differs → same deposits, different order. Still a real
  divergence: the filter keeps the first deposit seen per pubkey, so order decides which
  withdrawal credentials are checked for frontrun.
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

For more than one, run `scripts/ao_report_debug/keys_digest.py --selfcheck` against each
instance — it names the operator whose used-key rows fall short of its own
`usedSigningKeys`, with no second party involved.

Either way you end with a pubkey. `GET /v1/keys/<pubkey>` against both instances: one has it
`used: true`, the other does not, and the response names the module and operator.

### 3. Both match? Then it is the filter

```
Get pending deposits and not-yet-indexed lido keys.  lido_wc_list, genesis_fork_version
Collect valid pending deposits.                      signatures_verified,
                                                     invalid_signature_deposits,
                                                     invalid_keys
```

- `lido_wc_list` or `genesis_fork_version` differ → a configuration or contract difference,
  not a data one.
- `invalid_signature_deposits` differ → the BLS backends disagree. The per-deposit
  `Ignoring key. Invalid deposit signature` warnings give the exact tuples to re-verify
  against the other library.

### 4. The answer

```
Get pending lido validators.          value, total_amount_gwei
Pending Lido validators fingerprint.  count, digest, xor
```

One key differs → XOR the two `xor` values and you have it.

### 5. Half B — top-ups

```
Calculate pending top-ups balance.  value, validators_with_topups
Pending top-ups fingerprint.        count, digest, xor
```

`xor` names a single differing top-up outright. For more than one: this set is
`CL deposit queue ∩ used keys ∩ CL validator registry`, and all three are pinned above, so
steps 1 and 2 identify where it came from.

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
- **`Ignoring key. Invalid deposit signature`** / **`Ignoring key. Possible front run attack`** —
  a deposit excluded from the pending balance, logged with the full record so it can be
  re-verified against another BLS backend later.

All of the above are diagnostics: they log and continue, and never fail a report.

## Cost

Fingerprinting the mainnet used-key set (~485k entries) takes ~0.7 s, once per report
cycle, against a state fetch measured in minutes. Six lines of 250–400 bytes: under 2 KB a
cycle, and nothing bulky in the report logs.

Summary lines are deliberately small so they can be grepped and shipped; everything bulk is
on its own line and can be dropped by log shipping without losing the ability to *detect* a
divergence, only the ability to resolve one from the logs alone.
