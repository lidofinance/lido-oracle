# CHANGELOG

All notable changes to this project are documented in this file.

This changelog format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

[comment]: <> (## [Unreleased]&#40;https://github.com/lidofinance/lido-oracle&#41; - 2021-09-15)

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
