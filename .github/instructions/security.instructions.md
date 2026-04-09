# Security Review Instructions

Focus on crypto, smart contract, and private key security patterns.

## Private Key Security (CRITICAL)
- **BLOCK**: `MEMBER_PRIV_KEY` must NEVER appear in logs, print statements, or error messages
- **REQUIRE**: Private key variables only in `PRIVATE_ENV_VARS` dict in `src/variables.py`
- Check signature operations maintain cryptographic security standards

## Smart Contract Interactions
- **REQUIRE**: Role checks (`has_role()`) before state-changing operations
- Check transaction parameters use proper gas estimation (prevent DoS)
- Ensure contract addresses are checksummed and validated against known deployments

## Environment Variable Security
- New env vars must be categorized in `PRIVATE_ENV_VARS` vs `PUBLIC_ENV_VARS`
- Check default values don't expose secrets or infrastructure details
- Verify env var names don't leak sensitive information

## Web3 & API Security
- Check HTTP timeouts prevent DoS (not too short/long)
- Verify retry logic uses exponential backoff
- Ensure TLS verification enabled for external APIs
- Validate input beyond type hints (addresses, CIDs, numeric bounds)