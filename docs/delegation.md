## Delegation

Delegation allows separating protocol permissions from oracle hot keys. Instead of granting permissions directly to the oracle account, they are granted to a [DelegationContract](https://github.com/lidofinance/execution-delegation-framework), and the oracle executes calls through it.

This enables hot key rotation by the contract owner without governance voting.

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

The contract owner deploys a `DelegationContract` instance via `DelegationFactory` from the [execution-delegation-framework](https://github.com/lidofinance/execution-delegation-framework) repository.

#### 2. Grant protocol permissions

Governance grants oracle member permissions to the deployed `DelegationContract` address (not to the oracle hot key).

#### 3. Assign oracle as delegate

The contract owner calls `nominateDelegate(oracleAddress)` on the delegation contract, where `oracleAddress` is the oracle operator's account address (`MEMBER_PRIV_KEY`, or `MEMBER_PRIV_KEY_2` when preparing a rotation ahead of time).

- If the contract has no delegate yet, the nomination takes effect immediately (`InitialDelegateSet`).
- Otherwise, it starts a cooldown (`getCooldown()`): the nominated address becomes pending (`getPendingDelegate()` returns `(delegate, activeFrom)`) and only replaces the current delegate once `activeFrom` is reached. `getDelegate()` keeps returning the previous delegate until then.

#### 4. Configure the oracle

Set the environment variable:

```bash
DELEGATION_CONTRACT_ADDRESS=0x...  # deployed DelegationContract address
```

`MEMBER_PRIV_KEY_2` can additionally be configured with a second candidate key (see [Key rotation](#key-rotation)) — either a plain HashConsensus member or a candidate delegate.

### Signer resolution

There is no startup-time check of the delegation setup. Instead, the oracle re-resolves its active signing identity from scratch every reporting cycle (`SignerModule.process_members`), against the current HashConsensus member list:

- If the delegation contract is itself a HashConsensus member, the oracle reads its current delegate (`getDelegate()`) and checks whether it matches `MEMBER_PRIV_KEY` or `MEMBER_PRIV_KEY_2`.
- Otherwise, it looks for `MEMBER_PRIV_KEY` / `MEMBER_PRIV_KEY_2` directly among the plain HashConsensus members.
- If neither configured account matches (e.g. a rotation is still in its cooldown, or the oracle isn't a member at all), the oracle logs a warning and treats the cycle as dry mode — no report is submitted, and it retries the resolution on the next cycle instead of crashing.

The only startup-time check is that `MEMBER_PRIV_KEY` and `MEMBER_PRIV_KEY_2`, when both configured, must resolve to different addresses — the oracle fails fast otherwise, since rotating between two identical keys would silently do nothing.

### Key rotation

To rotate the oracle hot key with no downtime:

1. Configure the new key as `MEMBER_PRIV_KEY_2` and restart the oracle so it's loaded (env vars are only read at startup).
2. The contract owner calls `nominateDelegate(newOracleAddress)` on the delegation contract.
3. Once the cooldown elapses and the new delegate becomes active on-chain, the oracle picks it up automatically on its next reporting cycle — no further restart is needed.
4. Once rotation is confirmed, the old key can be dropped from `MEMBER_PRIV_KEY`/`MEMBER_PRIV_KEY_2` (requires a restart to take effect; leaving it configured is harmless, it will simply never match the on-chain delegate again).
