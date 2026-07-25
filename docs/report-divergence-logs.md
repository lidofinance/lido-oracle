# Diagnosing a report divergence from logs

When oracle members submit different report hashes for the same reference slot, they
disagree about an *input*, not about arithmetic. The three inputs large enough to hide a
disagreement are the beacon state (~900 MB), the Keys API used-key set (~485k keys,
~47 MB) and the pending deposit queue — none of which can be logged, and none of which can
be fetched back afterwards: the Keys API only answers for its current block, and a past
beacon state needs an archive node.

So the oracle logs fingerprints of them instead. Two members' log files are enough to say
which layer diverged, and usually to name the exact key or deposit responsible, without
either operator sharing any data.

## The fingerprint fields

Every fingerprinted set is logged as two lines: `<subject> fingerprint.` with a small
summary, and `<subject> sketch.` with the recovery data (~64 KB, emitted separately so log
shipping can drop it).

| Line          | Field           | Use                                                     |
|---------------|-----------------|----------------------------------------------------------|
| `fingerprint.`| `count`         | Did the two members even see the same number of entries?   |
| `fingerprint.`| `digest`        | keccak over the sorted set — equal digests mean identical sets. |
| `fingerprint.`| `xor`           | All entries XOR-ed together. If the sets differ by exactly one entry, XOR-ing the two members' values gives that entry, by hand, with no tooling. |
| `sketch.`     | `iblt`          | **Recovers the complete difference — every entry either side is missing, and which side is missing it.** |
| `sketch.`     | `bucket_counts` | Entries per 1/256 of the keyspace; a coarse fallback if the sketch cannot decode. |

### Recovering the differing entries

Pull the `sketch.` line for the same reference slot from each member and subtract them:

```bash
grep '"msg": "Used Lido keys sketch."' member-a.log | tail -1 > a.json
grep '"msg": "Used Lido keys sketch."' member-b.log | tail -1 > b.json

python3 scripts/reconcile_fingerprints.py a.json b.json \
    --left-name 0xa2432f5b --right-name 0xafd9bcb7
```

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

- `by_operator` and `by_operator_amount_gwei` on `Get pending lido validators.` — counts
  per (module, operator). A mass divergence shows up as one operator's count differing.
- `by_module` on `Used Lido keys fingerprint.` — the same at module granularity.
- `bucket_counts` on any `sketch.` line — 256 counts over the keyspace, showing whether the
  difference is concentrated or spread.

If you have only the `fingerprint.` line and exactly one entry differs (`count` differs by
1), you do not need the script at all:

```bash
# 48-byte pubkeys — Used Lido keys, Pending Lido keys, Pending Lido validators, CL validators
python3 -c "print('0x%096x' % (int('<xor_a>', 16) ^ int('<xor_b>', 16)))"

# 96-byte deposit records — Pending deposits: pubkey|wc|amount|slot
python3 -c "print('0x%0192x' % (int('<xor_a>', 16) ^ int('<xor_b>', 16)))"
```

Deposit entries deliberately omit the 96-byte signature: it would triple every sketch line
without identifying anything the other four fields do not. A deposit rejected *because* of
its signature is logged in full separately, and `pending_deposits_queue_digest` still
covers the signature, so a signature-only divergence is detected even though it is not
recovered per-entry.

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
| `Get pending lido validators.`                           | `total_amount_gwei` — the number `clPendingBalanceGwei` is built from — and per-operator counts and amounts. |
| `Pending Lido validators fingerprint.`                   | The final selected set.                                              |

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

Fingerprinting and sketching the mainnet used-key set (~485k entries) takes ~2.6 s, once
per report cycle, against a state fetch measured in minutes; the 40k-entry deposit queue
takes ~0.2 s. Each fingerprinted set adds one ~250 byte summary line and one sketch line —
~64 KB for pubkey sets, ~108 KB for deposit records — and there are five per accounting
cycle.
