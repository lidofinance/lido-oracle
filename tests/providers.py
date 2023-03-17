import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from web3 import Web3
from web3.module import Module
from web3.providers import JSONBaseProvider
from web3.types import RPCEndpoint, RPCResponse
from web3_multi_provider import MultiProvider

from src.providers.consensus.client import ConsensusClient
from src.providers.http_provider import HTTPProvider
from src.providers.keys.client import KeysAPIClient

BASE_FIXTURES_PATH = Path().absolute() / 'fixtures'


class NoMockException(Exception):
    def __init__(self, *args: object) -> None:
        args = list(args)
        args[0] += '\nPlease re-run tests with --update-responses flags. ' \
                   '\nSee tests/README.md for details.'
        super().__init__(*args)


class FromFile:
    responses: list[dict[str, Any]]

    def __init__(self, mock_path: Path):
        self.responses = []
        self.load_from_file(mock_path)

    @contextmanager
    def use_mock(self, mock_path: Path):
        previous_responses = self.responses
        self.load_from_file(mock_path)
        yield
        self.responses = previous_responses

    def load_from_file(self, mock_path: Path):
        mock_path = BASE_FIXTURES_PATH / mock_path
        if not mock_path.exists():
            return
        with open(mock_path, "r") as f:
            self.responses = json.load(f)


class UpdateResponses:
    def __init__(self):
        self.responses: list[dict[str, Any]] = []

    def save_responses(self, path: Path):
        path = BASE_FIXTURES_PATH / path
        if not self.responses:
            if os.path.exists(path):
                os.remove(path)
            return
        os.makedirs(path.parent, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.responses, f, indent=2)

    @contextmanager
    def use_mock(self, mock_path: Path):
        previous_responses = self.responses
        self.responses = []
        try:
            yield
        finally:
            self.save_responses(mock_path)
            self.responses = previous_responses


class ResponseFromFile(JSONBaseProvider, FromFile):
    def __init__(self, mock_path: Path):
        JSONBaseProvider.__init__(self)
        FromFile.__init__(self, mock_path)

    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        for response in self.responses:
            if response["method"] == method and json.dumps(response["params"]) == json.dumps(params):
                return response["response"]
        raise NoMockException('There is no mock for response')


class UpdateResponsesProvider(MultiProvider, UpdateResponses):

    def __init__(self, mock_path: Path, host):
        MultiProvider.__init__(self, host)
        UpdateResponses.__init__(self)
        self.from_file = ResponseFromFile(mock_path)

    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        try:
            response = self.from_file.make_request(method, params)
        except NoMockException:
            response = super().make_request(method, params)
        self.responses.append({"method": method, "params": params, "response": response})
        return response

    @contextmanager
    def use_mock(self, mock_path: Path):
        with self.from_file.use_mock(mock_path), super().use_mock(mock_path):
            yield


class ResponseFromFileHTTPProvider(HTTPProvider, Module, FromFile):
    def __init__(self, mock_path: Path, w3: Web3):
        self.w3 = w3
        HTTPProvider.__init__(self, host="")
        Module.__init__(self, w3)
        FromFile.__init__(self, mock_path)

    def _get(self, endpoint: str, path_param=None, query_params: Optional[dict] = None) -> dict | list:
        for response in self.responses:
            if response.get('url') == endpoint.format(path_param) and json.dumps(response["params"]) == json.dumps(query_params):
                return response["response"]
        raise NoMockException('There is no mock for response')


class UpdateResponsesHTTPProvider(HTTPProvider, Module, UpdateResponses):
    def __init__(self, mock_path: Path, host: str, w3: Web3):
        self.w3 = w3

        super().__init__(host)
        super(Module, self).__init__()
        self.responses = []
        self.from_file = ResponseFromFileHTTPProvider(mock_path, w3)

    def _get(self, endpoint: str, path_param=None, query_params: Optional[dict] = None) -> dict | list:
        try:
            response = self.from_file._get(endpoint.format(path_param), query_params)  # pylint: disable=protected-access
        except NoMockException:
            response = super()._get(endpoint.format(path_param), query_params)
        self.responses.append({"url": endpoint.format(path_param), "params": query_params, "response": response})
        return response

    @contextmanager
    def use_mock(self, mock_path: Path):
        with self.from_file.use_mock(mock_path), super().use_mock(mock_path):
            yield


class ResponseFromFileConsensusClientModule(ConsensusClient, ResponseFromFileHTTPProvider):
    pass


class UpdateResponsesConsensusClientModule(ConsensusClient, UpdateResponsesHTTPProvider):
    pass


class ResponseFromFileKeysAPIClientModule(KeysAPIClient, ResponseFromFileHTTPProvider):
    pass


class UpdateResponsesKeysAPIClientModule(KeysAPIClient, UpdateResponsesHTTPProvider):
    pass
