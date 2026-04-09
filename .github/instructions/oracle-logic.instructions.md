# Oracle Logic Validation

Review oracle-specific business logic for correctness and safety.

## Oracle Cycle Management
- Check changes don't break 24h/225-epoch accounting cycles or 8h/75-epoch ejector cycles
- Verify report submission sequence preserved: hash → data → extra data
- Check oracle member coordination and delay slots remain functional
- Check that edge cases tested are also documented in source code

## Protocol State Accuracy
- Validate consensus/execution layer data processing maintains mathematical accuracy
- Check TVL calculations handle edge cases (slashing, withdrawals, deposits)
- Ensure validator state transitions follow Ethereum protocol rules
- Flag changes that could corrupt beacon chain state tracking

## Safety Mechanisms
- Flag changes that could create oracle manipulation vectors
- Verify bunker mode triggers aren't bypassed or weakened
- Check negative rebase detection logic remains intact
- Ensure slashing penalty calculations preserved

## Data Integrity
- Verify cryptographic operations (signatures, hashes) maintain security
- Ensure external API changes don't introduce data corruption risks