from app.contracts import get_validators_keys, get_report_interval

# fmt: off
key_list = [
    b"\xa3\x84\xf0\xd7w\x1d\xe0'\x8e\x0e\x9b\x13$\xb1\xa0\x9b\xb8\xb3\xf8\xa6-\xff\xcd\xb87\x06\xe38vM\xe8\x93\xc6H\xd6\xab\xdbN\x02^\xf0\xe8ZQ\x1aw\xa2.",     # noqa E501
    b'\x91\x84Z\x12\xe0\x7fW\xbd\x1c\xa8\xba\x87\xc2\x97F\x1c u\xc7l\xe6\x00\xb9\xbb\x88\x99\xde\x00\x88\xf0\x92y\xee^R+\x84u\x9f\x1a\x85|J\x9a\x04\x8a5\x8b',  # noqa E501
    b'\x81\xcc\xb4\xd16\xcc&\x13\xad*\xce7#\xac\xd5\xaaD\xf6\xb2r\xe2\x10\xe0\x08tN\xfb\xb2Oh\xe4\xbfaB\x7f\x07\xdb\x99\xdd\xc6\x87F\x10\xd7\xe5\x13\x08h',     # noqa E501
    b'\xb8\xcd\x03\xfap-\xddG\xb8&\xa3P\x86Q\xe8@f_\x18h\xb3\x8cEp\x93\xcb\xcbi\x05\xf5\xa80P\xe3\x1b\x84p*\x9f\x19\x10\xc6\xff\xdf\x90\xad\xeb\x16'            # noqa E501
]


# fmt: on


class MockContract:
    class FunctionCallable:
        def __init__(self, res):
            self.res = res

        def call(self, *args):
            return self.res

    class Functions:
        def __init__(self, keys):
            self.keys = keys

        def getStakingProvidersCount(self, *args):
            return MockContract.FunctionCallable(1)

        def getTotalSigningKeyCount(self, *args):
            return MockContract.FunctionCallable(len(self.keys))

        def getSigningKey(self, registry_id, index):
            result = self.keys[index]
            return MockContract.FunctionCallable(result)

        def getReportIntervalDurationSeconds(self, *args):
            return MockContract.FunctionCallable(86400)

    def __init__(self, keys):
        self.functions = self.Functions(keys)


class MockProvider:
    class Account:
        def __init__(self):
            self.address = '0x' + '0' * 40

    class Eth:
        def __init__(self, cls):
            self.defaultAccount = cls

    def __init__(self):
        self.eth = self.Eth(self.Account())


contract = MockContract(key_list)
provider = MockProvider()
registry_id = 1


def test_validators_keys():
    get_validators_keys(contract, provider)


def test_get_report_interval():
    result = get_report_interval(contract, provider)
    assert result == 86400
