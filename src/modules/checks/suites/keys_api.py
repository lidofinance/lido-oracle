"""Keys api"""


def check_keys_api_provide_keys(web3, blockstamp):
    """Check that keys-api able to provide keys"""
    result = web3.kac.get_used_lido_keys(blockstamp)
    assert len(result) > 0, "keys-api service provide no keys"
