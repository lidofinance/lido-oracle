// SPDX-License-Identifier: GPL-3.0
pragma solidity 0.8.25;

interface IExecutor {
    function execute(address target, uint256 value, bytes calldata payload) external payable;
    function transferOwnership(address newOwner) external;
}

/// Runs a Dual Governance proposal's calls through its executor in one transaction, like the timelock does.
/// It has to own the executor while it runs, and hands the ownership back to `owner`.
contract BatchExecutor {
    function run(IExecutor executor, address[] calldata targets, bytes[] calldata payloads, address owner) external {
        for (uint256 i = 0; i < targets.length; ++i) {
            executor.execute(targets[i], 0, payloads[i]);
        }
        executor.transferOwnership(owner);
    }
}
