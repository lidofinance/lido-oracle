## Delegation

Delegation allows separating protocol permissions from oracle hot keys. Instead of granting permissions directly to the oracle account, they are granted to a [DelegationContract](https://github.com/lidofinance/delegation-execution-authority), and the oracle executes calls through it.

This enables instant hot key rotation by the contract admin without governance voting.

### How it works

```
Oracle (hot key)
    │
    │  calls execute(target, calldata)
    ▼
DelegationContract (holds protocol permissions)
    │
    │  forwards call as msg.sender
    ▼
Target contract (HashConsensus, AccountingOracle, ExitBusOracle, CSFeeOracle)
```

When delegation is enabled, the following calls are affected:

| Target contract                                                                            | Method                        | Module             |
|--------------------------------------------------------------------------------------------|-------------------------------|--------------------|
| [HashConsensus](https://docs.lido.fi/contracts/hash-consensus)                             | `submitReport`                | All                |
| [AccountingOracle](https://docs.lido.fi/contracts/accounting-oracle)                       | `submitReportData`            | Accounting         |
| [AccountingOracle](https://docs.lido.fi/contracts/accounting-oracle)                       | `submitReportExtraDataList`   | Accounting         |
| [AccountingOracle](https://docs.lido.fi/contracts/accounting-oracle)                       | `submitReportExtraDataEmpty`  | Accounting         |
| [ValidatorsExitBusOracle](https://docs.lido.fi/contracts/validators-exit-bus-oracle)       | `submitReportData`            | Ejector            |
| CSFeeOracle                                                                                | `submitReportData`            | Staking Module     |

The target contract sees `DelegationContract` as `msg.sender`, so all permissions must be granted to the delegation contract address, not to the oracle account.

### Setup

#### 1. Deploy delegation contract

The contract admin deploys a `DelegationContract` instance via `DelegationFactory` from the [delegation-execution-authority](https://github.com/lidofinance/delegation-execution-authority) repository.

#### 2. Grant protocol permissions

Governance grants oracle member permissions to the deployed `DelegationContract` address (not to the oracle hot key).

#### 3. Assign oracle as delegatee

The contract admin calls `assignDelegate(oracleAddress)` on the delegation contract, where `oracleAddress` is the oracle operator's account address.

#### 4. Configure the oracle

Set the environment variable:

```bash
DELEGATION_CONTRACT_ADDRESS=0x...  # deployed DelegationContract address
```

### Startup validation

On startup the oracle validates the delegation setup:

- If `DELEGATION_CONTRACT_ADDRESS` is not set, delegation is disabled and the oracle sends transactions directly.
- If set but `MEMBER_PRIV_KEY` is not configured (dry mode), validation is skipped.
- If the contract has no delegatee (`address(0)`), the oracle fails with `NotConfiguredError`.
- If the contract's delegatee does not match the oracle account, the oracle fails with `DelegateMismatchError`.

### Key rotation

To rotate the oracle hot key:

1. Admin calls `assignDelegate(newOracleAddress)` on the delegation contract.
2. Update `MEMBER_PRIV_KEY` in the oracle config to the new key.
3. Restart the oracle.

No governance vote is required.
