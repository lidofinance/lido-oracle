import json
import logging
from typing import Optional
from urllib.parse import urljoin

import requests

from .cid import CID
from .types import FetchError, IPFSProvider, UploadError

logger = logging.getLogger(__name__)


class Storacha(IPFSProvider):
    BRIDGE_URL = 'https://up.storacha.network/bridge'
    GATEWAY_URL = 'https://storacha.link/ipfs/'

    def __init__(
        self,
        auth_secret: str,
        authorization: str,
        space_did: str,
        timeout: int = 30
    ):
        """Initialize Storacha provider.

        Args:
            auth_secret: Storacha authentication secret
            authorization: Storacha authorization token
            space_did: Storacha space DID
            timeout: Request timeout in seconds
        """
        super().__init__()
        self.auth_secret = auth_secret
        self.authorization = authorization
        self.space_did = space_did

        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        return {
            'X-Auth-Secret': self.auth_secret,
            'Authorization': self.authorization,
            'Content-Type': 'application/json'
        }

    def _upload(self, content: bytes, name: Optional[str] = None) -> str:
        """Upload content to Storacha.

        Implemented according to Storacha HTTP-bridge specification:
        https://docs.storacha.network/how-to/http-bridge/
        
        Args:
            content: Content bytes to upload
            name: Not used in Storacha

        Returns:
            Root CID as string
        """
        car_file = self.car_converter.create_car_from_data(content)

        headers = self._get_headers()

        store_payload = {
            "tasks": [
                [
                    "store/add",
                    self.space_did,
                    {
                        "link": {"/": car_file.shard_cid},
                        "size": car_file.size
                    }
                ]
            ]
        }

        try:
            response = requests.post(self.BRIDGE_URL, headers=headers, data=json.dumps(store_payload), timeout=self.timeout)
            response.raise_for_status()
            resp_json = response.json()
        except requests.RequestException as ex:
            logger.error({"msg": "Store request failed", "error": str(ex)})
            raise UploadError(f"Store request failed: {ex}") from ex

        store_out = resp_json[0]['p']['out']
        if 'ok' in store_out:
            store_result = store_out['ok']
        else:
            error_msg = f"Storacha store/add error: {json.dumps(store_out)}"
            logger.error(error_msg)
            raise UploadError(error_msg)

        if store_result['status'] == 'upload':
            upload_url = store_result['url']
            upload_headers = store_result['headers']

            try:
                upload_response = requests.put(upload_url, headers=upload_headers, data=car_file.car_bytes, timeout=self.timeout)
                upload_response.raise_for_status()
            except requests.RequestException as ex:
                # Log error details without exposing upload URL with sensitive info
                error_info = getattr(ex, 'response', None)
                status_code = error_info.status_code if error_info is not None else 'unknown'
                logger.error({
                    "msg": "Upload request failed",
                    "error_type": type(ex).__name__,
                    "status_code": status_code
                })
                raise UploadError(f"Upload request failed: {ex}") from ex

        upload_payload = {
            "tasks": [
                [
                    "upload/add",
                    self.space_did,
                    {
                        "root": {"/": car_file.root_cid},
                        "shards": [{"/": car_file.shard_cid}]
                    }
                ]
            ]
        }

        try:
            response = requests.post(self.BRIDGE_URL, headers=headers, data=json.dumps(upload_payload), timeout=self.timeout)
            response.raise_for_status()
            resp_json = response.json()
        except requests.RequestException as ex:
            logger.error({"msg": "Upload/add request failed", "error": str(ex)})
            raise UploadError(f"Upload/add request failed: {ex}") from ex

        upload_out = resp_json[0]['p']['out']
        if 'ok' in upload_out:
            uploaded_cid = upload_out['ok']['root']['/']
        else:
            error_msg = f"Storacha upload/add error: {json.dumps(upload_out)}"
            logger.error(error_msg)
            raise UploadError(error_msg)

        return uploaded_cid

    def _fetch(self, cid: CID) -> bytes:
        """Fetch content from Storacha gateway.

        Args:
            cid: Content identifier

        Returns:
            Content bytes
        """
        try:
            response = requests.get(urljoin(self.GATEWAY_URL, str(cid)), timeout=self.timeout)
            response.raise_for_status()
            return response.content
        except requests.RequestException as ex:
            logger.error({"msg": "Fetch request failed", "error": str(ex)})
            raise FetchError(cid) from ex

    def pin(self, cid: CID) -> None:
        pass
