# @see https://github.com/multiformats/cid/blob/master/README.md#decoding-algorithm
def is_cid_v0(cid: str) -> bool:
    return cid.startswith("Qm") and len(cid) == 46
