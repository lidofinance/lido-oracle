from collections import UserString


class CID(UserString):
    def __repr__(self):
        return f"{self.__class__.__name__}({self.data})"


class CIDv0(CID):
    ...


class CIDv1(CID):
    ...


# @see https://github.com/multiformats/cid/blob/master/README.md#decoding-algorithm
def is_cid_v0(cid: str) -> bool:
    return cid.startswith("Qm") and len(cid) == 46
