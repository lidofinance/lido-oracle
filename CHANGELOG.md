# CHANGELOG

All notable changes to this project are documented in this file.

This changelog format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

[comment]: <> (## [Unreleased]&#40;https://github.com/lidofinance/lido-oracle&#41; - 2021-09-15)

## [8.0.0](https://github.com/lidofinance/lido-oracle/releases/tag/8.0.0) - 2026-05

### MaxEB, Delegation, and On-chain Telemetry

### Changed
- **Accounting**: Added MaxEB (EIP-7251) support — accounting module now handles validators with increased effective balance limits introduced in Pectra. Delegation contract integration added via `DELEGATION_CONTRACT_ADDRESS`, enabling the oracle to account for delegated stake in reports.
- **Ejector**: Updated exit order iterator to support meta groups and MaxEB validator semantics. Exit queue ordering is now aware of grouped validator sets and their consolidated balances.
- **CSM / CM**: Meta group interface updated to align with new staking module contracts. Reserve-deposit logic revised to allow non-zero rebate when distribution is zero.
- **Performance sidecars**: Performance collector gains a range info endpoint and caching for `_get_last_report` to reduce redundant node calls. Epoch batch processing is more efficient with iterator-based data fetching.

### Added
- On-chain telemetry: oracles now submit lightweight telemetry reports to a Data Bus contract on startup and after each report cycle. Telemetry is fire-and-forget with deduplication by report hash and supports a separate `TELEMETRY_ACCOUNT` key.
- Filebase IPFS provider added as an alternative to Kubo/Pinata. Storacha provider removed.
- `generate-build-info` Makefile target — embeds version, branch, and commit hash into `build-info.json` for reproducible build verification.

### Fixed
- Abnormal CL rebase calculation corrected for edge cases involving overwritten slashings after a full slashings buffer cycle.

## [7.1.0 VaultOS](https://github.com/lidofinance/lido-oracle/releases/tag/7.1.0) - 2026-02

### Fixed
- APR calculation is now based on seconds elapsed, not blocks elapsed
- Support for fresh devnets

## [7.0.0 VaultOS](https://github.com/lidofinance/lido-oracle/releases/tag/7.0.0) - 2025-12

### Vaults integration into AO

### Changed
- AO changes according to [LIP-31](https://github.com/lidofinance/lido-improvement-proposals/blob/develop/LIPS/lip-31.md)

## [6.0.0](https://github.com/lidofinance/lido-oracle/releases/tag/6.0.0) - 2025-07

### Support for Triggerable Withdrawals and CSM V2

### Changed
- AO and VEBO changes according to [LIP-30](https://github.com/lidofinance/lido-improvement-proposals/blob/develop/LIPS/lip-30.md)
- CSM changes according to [LIP-29](https://github.com/lidofinance/lido-improvement-proposals/blob/develop/LIPS/lip-29.md) 

## [5.1.0](https://github.com/lidofinance/lido-oracle/releases/tag/5.1.0) - 2025-04-01

### Pectra compatibility upgrade!

### Changed
- All changes according to [LIP-27](https://github.com/lidofinance/lido-improvement-proposals/blob/develop/LIPS/lip-27.md)

## [4.1.2](https://github.com/lidofinance/lido-oracle/releases/tag/4.1.2) - 2024-02-14

### CSM Introduce! 

### Added
- New oracle module according to spec: [LIP-26](https://github.com/lidofinance/lido-improvement-proposals/blob/develop/LIPS/lip-26.md)

## [3.0.0](https://github.com/lidofinance/lido-oracle/releases/tag/3.0.0) - 2023-01-01

### **Lido v2 big upgrade. [Details!](https://blog.lido.fi/introducing-lido-v2/)**

### Added
- Withdrawals support
- Staking router support

### Changed
- Oracle split in two separate modules: ejector and accounting

## [2.6.1](https://github.com/lidofinance/lido-oracle/releases/tag/2.6.1) - 2023-04-08
### Fixed
- Correctly handle missed slot.

## [2.4.0](https://github.com/lidofinance/lido-oracle/releases/tag/2.4.0) - 2022-10-04
### Changed
- Client for Prysm node has been changed to the same as for the lighthouse node.

## [2.3.1](https://github.com/lidofinance/lido-oracle/releases/tag/2.3.0) - 2022-07-22
### Minor
- Add backoff for beacon chain failed requests. ([#0162](https://github.com/lidofinance/lido-oracle/pull/162))

## [2.3.0](https://github.com/lidofinance/lido-oracle/releases/tag/2.3.0) - 2022-07-22
### Feature
- Support MultiProvider ([#0158](https://github.com/lidofinance/lido-oracle/pull/158))
- Alternate oracles ([#0156](https://github.com/lidofinance/lido-oracle/pull/156))
- Switch to poetry ([#0153](https://github.com/lidofinance/lido-oracle/pull/153))

### Minor
- Change CD/CI ([#0155](https://github.com/lidofinance/lido-oracle/pull/155))

## [2.2.0](https://github.com/lidofinance/lido-oracle/releases/tag/2.2.0) - 2022-04-06
### Feature
- Support Kiln testnet ([#0151](https://github.com/lidofinance/lido-oracle/pull/151))

## [2.1.1](https://github.com/lidofinance/lido-oracle/releases/tag/2.1.1) - 2022-02-14
### Fixed
- Performance issue ([#0146](https://github.com/lidofinance/lido-oracle/pull/146))

## [2.1.0](https://github.com/lidofinance/lido-oracle/releases/tag/v2.1.0) - 2022-01-19
### Feature
- Changelog added ([#0141](https://github.com/lidofinance/lido-oracle/pull/141))
- Added optional prefixes for prometheus metrics ([#0131](https://github.com/lidofinance/lido-oracle/pull/131))
- Added support for EIP-1559 ([#0128](https://github.com/lidofinance/lido-oracle/pull/128))
- Added teku support ([#0135](https://github.com/lidofinance/lido-oracle/pull/135))

### Changed
- Upgrade lido-sdk library to new one to increase performance ([#0135](https://github.com/lidofinance/lido-oracle/pull/135))
- Various improves for DockerFile (added multistage, permissions, healthcheck) ([#0132](https://github.com/lidofinance/lido-oracle/pull/132))

### Fixed
- Upgrade pip in DockerFile ([#0138](https://github.com/lidofinance/lido-oracle/pull/138))
- Remove secrets from logs ([#0137](https://github.com/lidofinance/lido-oracle/pull/137))
- Fixed DockerIgnore file ([#0130](https://github.com/lidofinance/lido-oracle/pull/130))

## [2.0.0](https://github.com/lidofinance/lido-oracle/releases/tag/v2.0.0) - 2021-04-29
### Feature
- Release 2.0.0 Lido oracle
