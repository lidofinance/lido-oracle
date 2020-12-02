#!/usr/bin/env bash

patch app/oracle.py < tests/patch
export PYTHONPATH=app/
pytest
patch -R app/oracle.py < tests/patch

