import json
import os
from collections import defaultdict
from dataclasses import dataclass
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


class NoMockException(Exception):
    def __init__(self, *args: object) -> None:
        args = list(args)
        args[0] += '\nPlease re-run tests with --save-responses or --update-responses flags. ' \
                   '\nSee tests/README.md for details.'
        super().__init__(*args)


class ResponseToFileProvider(MultiProvider):
    responses = []

    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        response = super().make_request(method, params)
        self.responses.append({"method": method, "params": params, "response": response})
        return response

    def save_responses(self, path: Path):
        if not self.responses:
            return
        os.makedirs(path.parent, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.responses, f, indent=2)


class ResponseFromFile(JSONBaseProvider):
    responses: list[dict[str, Any]]

    def __init__(self, mock_path: Path):
        super().__init__()
        if not mock_path.exists():
            self.responses = []
            return
        with open(mock_path, "r") as f:
            self.responses = json.load(f)

    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        for response in self.responses:
            if response["method"] == method and json.dumps(response["params"]) == json.dumps(params):
                return response["response"]
        raise NoMockException('There is no mock for response')


class UpdateResponsesProvider(ResponseToFileProvider):
    def __init__(self, mock_path: Path, host):
        super().__init__(host)
        self.from_file = ResponseFromFile(mock_path)

    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        try:
            response = self.from_file.make_request(method, params)
        except NoMockException:
            response = super().make_request(method, params)
        self.responses.append({"method": method, "params": params, "response": response})
        return response


@dataclass
class Mock:
    method: str
    params: Any
    result: Any


class MockProvider(JSONBaseProvider):
    def __init__(self, fallback_provider: JSONBaseProvider = None):
        super().__init__()
        self.fallback_provider = fallback_provider
        self.responses = defaultdict(dict)

    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        params_json = json.dumps(params)
        if method not in self.responses or params_json not in self.responses[method]:
            return self.fallback_provider.make_request(method, params)
        return self.responses[method][params_json]

    def add_mock(self, mock: Mock) -> None:
        self.responses[mock.method][json.dumps(mock.params)] = {"result": mock.result, "id": next(self.request_counter), "jsonrpc": "2.0"}

    def add_mocks(self, *mocks: Mock) -> None:
        for mock in mocks:
            self.add_mock(mock)

    def clear_mocks(self) -> None:
        self.responses = {}


class ResponseToFileHTTPProvider(HTTPProvider, Module):
    def __init__(self, host: str, w3: Web3):
        self.w3 = w3

        super().__init__(host)
        super(Module, self).__init__()

        self.responses = []

    def _get(self, url: str, params: Optional[dict] = None) -> tuple[dict | list, dict]:
        response = super()._get(url, params)
        self.responses.append({"url": url, "params": params, "response": response})
        return response

    def save_responses(self, path: Path):
        if not self.responses:
            return
        os.makedirs(path.parent, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.responses, f, indent=2)


class ResponseFromFileHTTPProvider(HTTPProvider, Module):
    responses: list[dict[str, Any]]

    def __init__(self, mock_path: Path, w3: Web3):
        self.w3 = w3
        super().__init__(host="")
        super(Module, self).__init__()
        if not mock_path.exists():
            self.responses = []
            return
        with open(mock_path, "r") as f:
            self.responses = json.load(f)

    def _get(self, url: str, params: Optional[dict] = None) -> dict | list:
        for response in self.responses:
            if response["url"] == url and json.dumps(response["params"]) == json.dumps(params):
                return response["response"]
        raise NoMockException('There is no mock for response')


class UpdateResponsesHTTPProvider(ResponseToFileHTTPProvider):
    def __init__(self, mock_path: Path, host: str, w3: Web3):
        super().__init__(host, w3)
        self.from_file = ResponseFromFileHTTPProvider(mock_path, w3)

    def _get(self, url: str, params: Optional[dict] = None) -> dict | list:
        try:
            response = self.from_file._get(url, params)
        except NoMockException:
            response = super()._get(url, params)
        self.responses.append({"url": url, "params": params, "response": response})
        return response


class ResponseToFileConsensusClientModule(ConsensusClient, ResponseToFileHTTPProvider):
    pass


class ResponseFromFileConsensusClientModule(ConsensusClient, ResponseFromFileHTTPProvider):
    pass


class UpdateResponsesConsensusClientModule(ConsensusClient, UpdateResponsesHTTPProvider):
    pass


class ResponseToFileKeysAPIClientModule(KeysAPIClient, ResponseToFileHTTPProvider):
    pass


class ResponseFromFileKeysAPIClientModule(KeysAPIClient, ResponseFromFileHTTPProvider):
    pass


class UpdateResponsesKeysAPIClientModule(KeysAPIClient, UpdateResponsesHTTPProvider):
    pass
