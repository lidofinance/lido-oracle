# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import os

import typing as t

from lido_sdk import Lido
from lido_sdk.config import (
    MULTICALL_MAX_BUNCH,
    MULTICALL_MAX_WORKERS,
    MULTICALL_MAX_RETRIES,
    MULTICALL_POOL_EXECUTOR_TIMEOUT,
    VALIDATE_POOL_EXECUTOR_TIMEOUT,
)
from lido_sdk.methods.typing import OperatorKey


def get_validators_keys(w3) -> t.List[OperatorKey]:
    """Fetch all validator's keys from registry"""
    lido = Lido(
        w3,
        MULTICALL_MAX_BUNCH=int(os.getenv('MULTICALL_MAX_BUNCH', MULTICALL_MAX_BUNCH)),
        MULTICALL_MAX_WORKERS=int(os.getenv('MULTICALL_MAX_WORKERS', MULTICALL_MAX_WORKERS)),
        MULTICALL_MAX_RETRIES=int(os.getenv('MULTICALL_MAX_RETRIES', MULTICALL_MAX_RETRIES)),
        MULTICALL_POOL_EXECUTOR_TIMEOUT=int(os.getenv('MULTICALL_POOL_EXECUTOR_TIMEOUT', MULTICALL_POOL_EXECUTOR_TIMEOUT)),
        VALIDATE_POOL_EXECUTOR_TIMEOUT=int(os.getenv('VALIDATE_POOL_EXECUTOR_TIMEOUT', VALIDATE_POOL_EXECUTOR_TIMEOUT)),
    )
    lido.get_operators_indexes()
    lido.get_operators_data()
    return list(map(lambda x: x['key'], lido.get_operators_keys()))
