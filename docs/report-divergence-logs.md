# Diagnosing a report divergence from logs

When oracle members submit different report hashes for the same reference slot, they
disagree about an *input*, not about arithmetic. The two inputs large enough to hide a
disagreement are the beacon state (~900 MB) and the Keys API used-key set (~485k keys,
~47 MB). Neither can be logged as-is, so the oracle logs a single digest of each. Two
members compare one line apiece and learn which layer diverged, without either operator
sharing any data.

Fingerprints go on the *inputs* only — what the oracle was handed, not what it computed
from them. Everything downstream follows deterministically, so equal inputs and a differing
report means the members are running different code, which `Oracle startup.` already
reports.

## What the digest is, and is not

Each fingerprinted response is one log line, `<subject> fingerprint.`, carrying a `digest`
and enough context to say which response it covers.

**Equal digests mean the responses were identical. That is the whole claim.** The digest
covers every field of the response; it deliberately does not say *which* field or entry
differs. Naming the culprit needs the data itself, and the data is still available — from
the live Keys API instances, which still disagree, or from an archive node. Pre-staging an
answer in the logs would cost orders of magnitude more volume every cycle for a case that
has occurred once.

The digest is taken over the *parsed* response, not over the bytes on the wire: consensus
clients serialise the same state differently — key order, whitespace, numeric formatting —
so a digest of the raw body would differ between two correct members every cycle and mean
nothing.

Two orderings are used, because the two responses differ in whether row order carries
meaning:

| Response | Ordering | Why |
|---|---|---|
| Beacon state | ordered | List order is part of the state. A validator's position *is* its index, and the deposit queue is processed in order — the pending-deposit filter keeps the first deposit seen per pubkey, so a reordering alone changes which withdrawal credentials are checked for frontrun. |
| Keys API | unordered | The Keys API promises no row order, so an order-sensitive digest would report two identical key sets as different. Entries are compared as a multiset: a key served twice still differs from a key served once. |

## What to compare, in order

Work down the pipeline; the first line whose values differ names the layer at fault.

| `msg` | Covers |
|---|---|
| `Beacon state fingerprint.` | The whole `BeaconStateView`: validators, balances, slashings, the pending deposit queue, pending partial withdrawals and consolidations. Logged with `state_root` and `slot`. |
| `Keys API response.` | Per request: the `elBlockSnapshot` the answer was served at, including `lastChangedBlockHash`, and the response size. |
| `Keys API used keys fingerprint.` | The whole `v1/keys?used=true` response. **This is where the 2026-07-25 split lived.** |
| `Keys API module operators keys fingerprint.` | The whole `v1/modules/{}/operators/keys?used=true` response — keys, module and operator records. An input to the CSM and CM reward split. |
| `Get pending deposits and not-yet-indexed lido keys.` | `lido_wc_list` and `genesis_fork_version` — the two constants the deposit filter depends on. |
| `Collect valid pending deposits.` | How many deposits were kept and how many keys were rejected. Each rejected deposit is on its own line, in full. |
| `Get pending lido validators.` | `total_amount_gwei` — half of what `clPendingBalanceGwei` is built from. |

## Worked example: the pending balance differs

Two members, same reference slot, different `clPendingBalanceGwei`.

### 0. Which half?

```
Calculate CL pending validators balance.   value  ← the number in the report
Calculate new pending validators balance.  value  ← half A: not-yet-activated keys
Calculate pending top-ups balance.         value  ← half B: top-ups to active validators
```

### 1. Rule the consensus layer in or out

```
Beacon state fingerprint.   state_root, slot, digest
```

- `state_root` differs → the members read *different states*. Not a data bug; check the
  reference slot and for a reorg.
- `state_root` equal, `digest` equal → **the state is provably identical**, including the
  deposit queue and its order. Go to step 2.
- `state_root` equal, `digest` differs → a consensus client returned a state inconsistent
  with the root it was handed. That is a client bug; escalate with both digests and the
  `state_root`, and re-fetch the state from an archive node to see which member's client
  was wrong.

### 2. Rule the Keys API in or out

```
Keys API response.               el_block_snapshot{blockNumber, blockHash, lastChangedBlockHash}
Keys API used keys fingerprint.  digest
```

- Equal `lastChangedBlockHash` → both instances consumed the same on-chain key updates, so
  a differing digest below is the instance's own bookkeeping, not a different view of the
  chain.
- `digest` differs → the two instances served different key sets.

Usually you will not get this far, because the oracle already names the culprit on one
member's own data. `_kapi_sanity_check_by_operator` requires the Keys API to return every
key index in `[0, total_deposited_validators)` for each operator, and logs the gap:

```
Used keys from KAPI mismatched.   staking_module_address, operator_id,
                                  missing_indexes, missing_count
```

If neither member logged that — the sets differ without either being short of its on-chain
counters — go to the live data. Both instances still disagree today, so
`GET /v1/keys?used=true` against each and diffing the pubkeys names the keys, and
`GET /v1/keys/<pubkey>` names the module and operator.

### 3. Both match? Then it is the filter

```
Get pending deposits and not-yet-indexed lido keys.  lido_wc_list, genesis_fork_version
Collect valid pending deposits.                      valid_keys, invalid_keys
Ignoring key. Invalid deposit signature              value, withdrawal_credentials, amount,
                                                     slot, signature
```

- `lido_wc_list` or `genesis_fork_version` differ → a configuration or contract difference,
  not a data one.
- The `Ignoring key.` warnings differ → the BLS backends disagree. Each warning carries the
  full deposit, which is the exact tuple to re-verify against the other library — the state
  it came from will be gone by then.

### 4. Inputs all match?

```
Get pending lido validators.        value, total_amount_gwei
Calculate pending top-ups balance.  value, validators_with_topups
Oracle startup.                     variables{version, branch, commit, ...}
```

The selected pending validators and the top-ups are *derived* — nothing is fingerprinted
here on purpose. Both follow deterministically from the inputs above, so if those match and
these counts do not, the members are running different code. Compare `Oracle startup.`, then
replay the inputs locally against each build.

## Cost

Measured at mainnet scale (1.1M validators, 485k used keys) on a laptop:

| Response | Time |
|---|---|
| Beacon state | ~5.5 s |
| Keys API used keys | ~3.5 s |

Once per report cycle each, against a state fetch measured in minutes. Bunker mode fetches
two additional historical states and pays the state cost again for each; they are
distinguishable by `state_root`.

Each line is under 200 bytes, so the whole scheme adds well under 1 KB per cycle and nothing
bulky to the report logs.
