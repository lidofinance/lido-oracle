import subprocess
import pytest
from app.oracle import prompt


@pytest.fixture()
def input_y(monkeypatch):
    monkeypatch.setattr('builtins.input', lambda: 'y')


@pytest.fixture()
def input_n(monkeypatch):
    monkeypatch.setattr('builtins.input', lambda: 'n')


def test_promt_return_true(input_y):
    result = prompt('Should we sent this TX? [y/n]: ', '')
    assert result is True


def test_promt_return_false(input_n):
    result = prompt('Should we sent this TX? [y/n]: ', '')
    assert result is False


def test_oracle_with_sent_tx():
    result = subprocess.run(['python3', './app/oracle.py'], universal_newlines=True, input='n', capture_output=True,
                            text=True)
    assert 'not send' in result.stdout


def test_oracle_without_sent_tx():
    result = subprocess.run(['python3', './app/oracle.py'], universal_newlines=True, input='y', capture_output=True,
                            text=True)
    assert 'send transaction' in result.stdout
