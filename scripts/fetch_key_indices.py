#!/usr/bin/env python3
"""
Script to fetch validator key indices from Lido Keys API and encode exit request data.

This script:
1. Accepts KAPI URL, CL URL, node operator ID, and a list of public keys
2. Calls v1/keys?operatorIndex={id} to get key data with indices
3. Fetches validator indices from Consensus Layer using public keys
4. Maps public keys to their indices from the API response
5. Encodes the data similar to the oracle's approach

Example usage:
    python scripts/fetch_key_indices.py \
        --kapi-url ... \
        --cl-url ... \
        --operator-id 38 \
        --module-id 1 \
        --public-keys 0x9230d23e9e516d950be5ade42ae270021062628cea83b6a8a5207e5e6fe36af320545257306b968556d9f9a4648a2f9e
"""

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests
from eth_typing import HexStr


@dataclass
class KeyData:
    """Key data structure matching the Keys API response"""
    index: int
    key: HexStr
    depositSignature: HexStr
    operatorIndex: int
    used: bool
    moduleAddress: HexStr
    vetted: bool


@dataclass
class ValidatorInfo:
    """Validator information from Consensus Layer"""
    index: int
    pubkey: HexStr
    status: str


@dataclass
class ExitRequestInput:
    """Exit request input structure"""
    moduleId: int
    nodeOpId: int
    valIndex: int
    valPubkey: HexStr
    valPubKeyIndex: int


class KeysAPIClient:
    """Client for interacting with Lido Keys API"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
    
    def get_operator_keys(self, operator_index: int) -> List[KeyData]:
        """
        Fetch all keys for a specific operator using v1/keys?operatorIndex={id}
        
        Args:
            operator_index: The node operator index
            
        Returns:
            List of KeyData objects
        """
        url = f"{self.base_url}/v1/keys"
        params = {"operatorIndex": operator_index}
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            keys = []
            
            for key_item in data.get("data", []):
                keys.append(KeyData(
                    index=key_item["index"],
                    key=HexStr(key_item["key"]),
                    depositSignature=HexStr(key_item["depositSignature"]),
                    operatorIndex=key_item["operatorIndex"],
                    used=key_item["used"],
                    moduleAddress=HexStr(key_item["moduleAddress"]),
                    vetted=key_item["vetted"]
                ))
            
            return keys
            
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch keys from API: {e}")
        except (KeyError, ValueError) as e:
            raise Exception(f"Invalid API response format: {e}")


class ConsensusLayerClient:
    """Client for interacting with Consensus Layer"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
    
    def get_validator_by_pubkey(self, pubkey: HexStr) -> Optional[ValidatorInfo]:
        """
        Fetch validator information by public key from CL
        
        Args:
            pubkey: Validator public key
            
        Returns:
            ValidatorInfo object or None if not found
        """
        # Normalize pubkey format
        if pubkey.startswith('0x'):
            normalized_pubkey = pubkey
        else:
            normalized_pubkey = f"0x{pubkey}"
        
        url = f"{self.base_url}/eth/v1/beacon/states/head/validators/{normalized_pubkey}"
        
        try:
            response = self.session.get(url, timeout=30)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            
            data = response.json()
            validator_data = data.get("data")
            
            if not validator_data:
                return None
            
            return ValidatorInfo(
                index=int(validator_data["index"]),
                pubkey=HexStr(validator_data["validator"]["pubkey"]),
                status=validator_data["status"]
            )
            
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch validator from CL: {e}")
        except (KeyError, ValueError) as e:
            raise Exception(f"Invalid CL response format: {e}")
    
    def get_validators_by_pubkeys(self, pubkeys: List[HexStr]) -> Dict[HexStr, ValidatorInfo]:
        """
        Fetch multiple validators by their public keys
        
        Args:
            pubkeys: List of validator public keys
            
        Returns:
            Dictionary mapping pubkey to ValidatorInfo
        """
        validators = {}
        
        for pubkey in pubkeys:
            print(f"Fetching validator info for {pubkey[:10]}...")
            validator_info = self.get_validator_by_pubkey(pubkey)
            if validator_info:
                validators[pubkey.lower()] = validator_info
            else:
                print(f"Warning: Validator not found for pubkey {pubkey}")
        
        return validators


def create_pubkey_to_index_mapping(keys: List[KeyData]) -> Dict[HexStr, int]:
    """
    Create a mapping from public key to key index
    
    Args:
        keys: List of key data from the API
        
    Returns:
        Dictionary mapping public key to index
    """
    return {key.key.lower(): key.index for key in keys}


def validate_public_keys(requested_keys: List[HexStr], available_keys: Dict[HexStr, int]) -> List[HexStr]:
    """
    Validate that all requested public keys are available for the operator
    
    Args:
        requested_keys: List of public keys to validate
        available_keys: Dictionary of available keys from API
        
    Returns:
        List of missing keys (empty if all keys are found)
    """
    missing_keys = []
    for key in requested_keys:
        normalized_key = key.lower()
        if normalized_key not in available_keys:
            missing_keys.append(key)
    return missing_keys


def create_exit_requests(
    module_id: int,
    operator_id: int,
    public_keys: List[HexStr],
    validators_info: Dict[HexStr, ValidatorInfo],
    key_index_mapping: Dict[HexStr, int]
) -> List[ExitRequestInput]:
    """
    Create exit request inputs for the given parameters
    
    Args:
        module_id: Staking module ID
        operator_id: Node operator ID
        public_keys: List of validator public keys
        validators_info: Dictionary of validator information from CL
        key_index_mapping: Mapping from public key to key index
        
    Returns:
        List of ExitRequestInput objects
    """
    exit_requests = []
    
    for pub_key in public_keys:
        normalized_key = pub_key.lower()
        
        # Get key index from Keys API
        key_index = key_index_mapping.get(normalized_key)
        if key_index is None:
            raise ValueError(f"Key index not found for public key: {pub_key}")
        
        # Get validator index from CL
        validator_info = validators_info.get(normalized_key)
        if validator_info is None:
            raise ValueError(f"Validator not found in CL for public key: {pub_key}")
        
        exit_requests.append(ExitRequestInput(
            moduleId=module_id,
            nodeOpId=operator_id,
            valIndex=validator_info.index,
            valPubkey=pub_key,
            valPubKeyIndex=key_index
        ))
    
    return exit_requests


def encode_exit_requests(exit_requests: List[ExitRequestInput]) -> bytes:
    """
    Encode exit requests into bytes format
    
    Args:
        exit_requests: List of exit request inputs
        
    Returns:
        Encoded bytes data
    """
    # Constants for encoding
    MODULE_ID_LENGTH = 8
    NODE_OPERATOR_ID_LENGTH = 8
    VALIDATOR_INDEX_LENGTH = 8
    VALIDATOR_PUB_KEY_LENGTH = 48
    VAL_PUB_KEY_INDEX_LENGTH = 8
    
    result = b''
    
    for request in exit_requests:
        # Module ID (8 bytes)
        result += request.moduleId.to_bytes(MODULE_ID_LENGTH, byteorder='big')
        
        # Node Operator ID (8 bytes)
        result += request.nodeOpId.to_bytes(NODE_OPERATOR_ID_LENGTH, byteorder='big')
        
        # Validator Index (8 bytes)
        result += request.valIndex.to_bytes(VALIDATOR_INDEX_LENGTH, byteorder='big')
        
        # Validator Public Key (48 bytes)
        if request.valPubkey.startswith('0x'):
            pubkey_hex = request.valPubkey[2:]
        else:
            pubkey_hex = request.valPubkey
            
        pubkey_bytes = bytes.fromhex(pubkey_hex)
        if len(pubkey_bytes) != VALIDATOR_PUB_KEY_LENGTH:
            raise ValueError(f'Invalid public key length: {len(pubkey_bytes)} bytes, expected {VALIDATOR_PUB_KEY_LENGTH}')
        result += pubkey_bytes
        
        # Validator Public Key Index (8 bytes)
        result += request.valPubKeyIndex.to_bytes(VAL_PUB_KEY_INDEX_LENGTH, byteorder='big')
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Fetch key indices from Lido Keys API and validator indices from CL, then encode exit request data')
    parser.add_argument('--kapi-url', required=True, help='Keys API base URL (e.g., https://keys-api.lido.fi)')
    parser.add_argument('--cl-url', required=True, help='Consensus Layer API base URL (e.g., https://beacon-api.example.com)')
    parser.add_argument('--operator-id', type=int, required=True, help='Node operator ID')
    parser.add_argument('--module-id', type=int, required=True, help='Staking module ID')
    parser.add_argument('--public-keys', nargs='+', required=True, help='List of validator public keys')
    parser.add_argument('--output-format', choices=['json', 'hex', 'bytes'], default='json', help='Output format')
    parser.add_argument('--output-file', help='Output file path (optional)')
    
    args = parser.parse_args()
    
    try:
        # Initialize API clients
        kapi_client = KeysAPIClient(args.kapi_url)
        cl_client = ConsensusLayerClient(args.cl_url)
        
        print(f"Fetching keys for operator {args.operator_id} from {args.kapi_url}")
        
        # Fetch operator keys from Keys API
        operator_keys = kapi_client.get_operator_keys(args.operator_id)
        print(f"Found {len(operator_keys)} keys for operator {args.operator_id}")
        
        # Create mapping from public key to key index
        key_index_mapping = create_pubkey_to_index_mapping(operator_keys)
        
        # Validate that all requested keys are available
        missing_keys = validate_public_keys(args.public_keys, key_index_mapping)
        if missing_keys:
            print(f"Error: The following public keys were not found for operator {args.operator_id}:")
            for key in missing_keys:
                print(f"  - {key}")
            sys.exit(1)
        
        print(f"Fetching validator indices from CL for {len(args.public_keys)} validators...")
        
        # Fetch validator information from CL
        validators_info = cl_client.get_validators_by_pubkeys(args.public_keys)
        
        # Check if all validators were found in CL
        missing_validators = []
        for pubkey in args.public_keys:
            if pubkey.lower() not in validators_info:
                missing_validators.append(pubkey)
        
        if missing_validators:
            print(f"Error: The following validators were not found in CL:")
            for pubkey in missing_validators:
                print(f"  - {pubkey}")
            sys.exit(1)
        
        # Create exit requests
        exit_requests = create_exit_requests(
            args.module_id,
            args.operator_id,
            args.public_keys,
            validators_info,
            key_index_mapping
        )
        
        print(f"Created {len(exit_requests)} exit requests")
        
        # Generate output based on format
        if args.output_format == 'json':
            output_data = {
                "exit_requests": [
                    {
                        "moduleId": req.moduleId,
                        "nodeOpId": req.nodeOpId,
                        "valIndex": req.valIndex,
                        "valPubkey": req.valPubkey,
                        "valPubKeyIndex": req.valPubKeyIndex
                    }
                    for req in exit_requests
                ],
                "encoding_info": {
                    "total_requests": len(exit_requests),
                    "operator_id": args.operator_id,
                    "module_id": args.module_id
                },
                "validator_details": [
                    {
                        "pubkey": info.pubkey,
                        "validator_index": info.index,
                        "status": info.status
                    }
                    for info in validators_info.values()
                ]
            }
            output = json.dumps(output_data, indent=2)
            
        elif args.output_format == 'hex':
            encoded_bytes = encode_exit_requests(exit_requests)
            output = f"0x{encoded_bytes.hex()}"
            
        elif args.output_format == 'bytes':
            encoded_bytes = encode_exit_requests(exit_requests)
            output = str(list(encoded_bytes))
        
        # Output results
        if args.output_file:
            with open(args.output_file, 'w') as f:
                f.write(output)
            print(f"Output written to {args.output_file}")
        else:
            print("\nOutput:")
            print(output)
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main() 