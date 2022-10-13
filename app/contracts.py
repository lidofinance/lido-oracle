# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import typing as t

from lido_sdk import Lido
from lido_sdk.methods.typing import OperatorKey


def get_validators_keys(w3) -> t.List[OperatorKey]:
    """Fetch all validator's keys from registry"""
    lido = Lido(w3)
    lido.get_operators_indexes()
    lido.get_operators_data()
    return list(map(lambda x: x['key'], lido.get_operators_keys()))
