# Lido Oracle GitHub Copilot Instructions

## Overview
Lido Oracle is critical DeFi infrastructure processing $40B+ in staked ETH. Apply security-first mindset to ALL code changes - any vulnerability could impact billions in user funds.

## Priority Review Areas

**SECURITY FIRST**: Apply heightened security review to all code changes - flag potential vulnerabilities, unsafe patterns, and security regressions
**ORACLE LOGIC**: Verify cycle timing, report sequences, and consensus mechanisms remain intact
**TESTING STANDARDS**: Enforce AAA naming (`test_method__scenario__expected`) and conftest fixtures if possible
**DOCUMENTATION**: Ensure env var and API changes update corresponding docs

## Key Patterns
- Environment variables: Use `PRIVATE_ENV_VARS` vs `PUBLIC_ENV_VARS` separation
- Private keys: Must only appear in `PRIVATE_ENV_VARS`, never logged/printed

## Review Approach
- Explain WHY flagged issues are problematic
- Focus on business logic correctness and safety
- Reference security implications for DeFi context
- Provide constructive suggestions with examples