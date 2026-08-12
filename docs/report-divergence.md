# Report divergence

Members that submit different report hashes for the same reference slot disagree about an
*input*. The two inputs large enough to hide a disagreement — the beacon state and the Keys
API used-key set — are too big to log, so the oracle logs one digest of each instead. Two
operators compare a line apiece to find the layer they disagree about:

| `msg` | Covers |
|---|---|
| `Beacon state fingerprint.` | The whole consensus layer state response, with `state_root` and `slot`. |
| `Keys API used keys fingerprint.` | The whole `v1/keys?used=true` response. |
| `Keys API module operators keys fingerprint.` | The whole `v1/modules/{}/operators/keys?used=true` response. |

Equal digests mean both members read the same inputs — that is the whole claim. Each digest
covers every field the oracle parses out of the response, in the order it arrived. It is
deliberately not a hash of the raw body: the beacon state envelope carries per-node
`execution_optimistic`, so two correct members would differ whenever one node's execution
client lags. Fields the oracle never reads are outside the digest, which is the right scope
— a report can only diverge over something it was computed from.

A digest does not say *which* entry differs. To name it, use `Used keys from KAPI
mismatched.` (logged against the operator's on-chain deposit count) or query the Keys API
instances directly, since a difference that can move a report is still there afterwards.

`Beacon state fingerprint.` appears more than once per accounting cycle. The bunker check
reads the state at the previous report's reference slot as well as at this one, and a frame
whose CL rebase looks abnormal reads several more. Match the lines by `state_root` and
`slot` first — digests taken at different slots say nothing about each other.

Compare in pipeline order and stop at the first line that differs: `Beacon state
fingerprint.`, then `Keys API response.` (the `elBlockSnapshot` each answer was served at)
and the Keys API digests. If every input matches and the reports still differ, the members
are running different code: compare `Oracle startup.`.
