
def check_eth_call_availability(accounting, blockstamp):
    """Check that execution-client able to make eth_call on the provided blockstamp"""
    accounting.get_chain_config(blockstamp)


def check_balance_availability(web3, blockstamp):
    """Check that execution-client able to get balance on the provided blockstamp"""
    web3.lido_contracts.get_withdrawal_balance_no_cache(blockstamp)


def check_events_range_availability(ejector, blockstamp):
    """Check that execution-client able to get event logs on the provided range"""
    chain_config = ejector.get_chain_config(blockstamp)
    ejector.prediction_service.get_rewards_per_epoch(blockstamp, chain_config)
