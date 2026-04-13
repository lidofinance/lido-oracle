---
applyTo: "{README.md,docs/**,.env.example,src/variables.py,src/**}"
---

# Documentation Update Requirements

Ensure code changes include corresponding documentation updates.

## Environment Variable Documentation
- Flag missing README updates when `src/variables.py` adds new env vars
- Flag missing `.env.example` updates when a new required or commonly used env var is introduced
- Check examples don't contain real credentials
- Check renamed or removed env vars are reflected in README examples and operator-facing docs

## Consistency Checks
- Verify examples in documentation match actual patterns
- If Docker, compose, workflow, or startup commands change, verify README instructions still work
- If behavior of oracle phases, module names, metrics, or public HTTP/API surfaces changes, ensure the relevant docs are updated
