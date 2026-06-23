---
applyTo: "{src/modules/oracles/**/*.py,src/services/**/*.py,src/providers/**/*.py,src/web3py/**/*.py}"
---

# Oracle Logic Validation

Review oracle-specific business logic for correctness and safety.

## Oracle Cycle Management
- Check changes don't break 24h/225-epoch accounting cycles or 5h/45-epoch ejector cycles
- Verify report submission sequence preserved: hash → data → extra data
- Check oracle member coordination and delay slots remain functional
- Verify logic still uses finalized/reference data where required and does not accidentally switch to head/non-finalized state
- Flag changes that mix report-time state with latest-chain state in a way that could produce inconsistent submissions

## Module-Specific Focus
- `accounting`: review bunker mode, safe-border logic, withdrawal finalization, share-rate math, and consistency between main report data and extra data
- `ejector`: review exit ordering, demand coverage, predictable balance calculations, and module/operator weighting
- `csm` / `cm`: review performance data freshness, IPFS publish flow, and consistency between sidecar data and on-chain reporting
- `check` and provider/runtime code: review failure handling, stale-cache behavior, retries, and degraded-mode assumptions

## Protocol State Accuracy
- Validate consensus/execution layer data processing maintains mathematical accuracy
- Check TVL calculations handle edge cases (slashing, withdrawals, deposits)
- Ensure validator state transitions follow Ethereum protocol rules
- Flag changes that could corrupt beacon chain state tracking
- Check ref-slot based calculations, timestamps, and share-rate precision remain unchanged unless the protocol explicitly requires it
- Review multi-phase accounting reports for consistency between main report data and extra data payloads

## Safety Mechanisms
- Flag changes that could create oracle manipulation vectors
- Verify bunker mode triggers aren't bypassed or weakened
- Check negative rebase detection logic remains intact
- Ensure slashing penalty calculations preserved
- Review safe-border and withdrawal finalization logic carefully: bunker mode depends on correct handling of new-request, associated-slashing, and negative-rebase borders
- Verify contract-address refresh logic still clears stale cached state when deployments change

## Data Integrity
- Verify cryptographic operations (signatures, hashes) maintain security
- Ensure external API changes don't introduce data corruption risks
- Check retry/fallback behavior does not hide inconsistent provider responses or turn deterministic failures into silent partial data use
