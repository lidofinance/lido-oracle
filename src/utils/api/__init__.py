"""
Module for integrating with third-party infrastructure services.

This module provides low-level integrations with external infrastructure tools, such as alerting or monitoring systems.
For business-logic-specific integrations (e.g., Ethereum staking or oracle operations), use the implementations in
`/src/providers/` instead.

"""
from .opsgenie import opsgenie_api
