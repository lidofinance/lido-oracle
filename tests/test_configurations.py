import regex
import os
import subprocess
import ast

from oracle import DEFAULT_GAS_LIMIT, DEFAULT_SLEEP
from tests.utils import get_log_lines


def test_no_considered_withdrawals_from_epoch():
    env = os.environ.copy()
    env.pop('CONSIDER_WITHDRAWALS_FROM_EPOCH', None)
    assert env.get('MEMBER_PRIV_KEY'), 'MEMBER_PRIV_KEY must be set in environment variables'
    env['DAEMON'] = '1'
    env['FORCE_DO_NOT_USE_IN_PRODUCTION'] = '1'
    custom_sleep = 42
    env['SLEEP'] = f'{custom_sleep}'
    with subprocess.Popen(
        ['python3', '-u', './app/oracle.py'],
        bufsize=0,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    ) as proc:
        lines = get_log_lines(proc, n_lines=100, timeout=30, stop_on_substring='We are in DAEMON mode. Sleep')
        err_line = lines[-1]
        assert 'CONSIDER_WITHDRAWALS_FROM_EPOCH is not set' in err_line
    assert proc.returncode == 1, f'output {lines}'


def test_no_priv_key():
    env = os.environ.copy()
    env['CONSIDER_WITHDRAWALS_FROM_EPOCH'] = '32'
    env.pop('MEMBER_PRIV_KEY', None)
    env.pop('DAEMON', None)
    with subprocess.Popen(
        ['python3', '-u', './app/oracle.py'],
        bufsize=0,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    ) as proc:
        lines = get_log_lines(proc, n_lines=11)
        match = [i for i, line in enumerate(lines) if regex.match(r'.* Connected to .* network', line)]
        assert len(match) == 1, f'bad output {lines}'
        index = match[0]
        assert lines[index + 1].endswith('Injecting PoA compatibility middleware')
        assert lines[index + 2].endswith('MEMBER_PRIV_KEY not provided, running in read-only (DRY RUN) mode')
        out, err = proc.communicate(timeout=30)
        proc.wait()
    assert proc.returncode == 0, f'invalid returncode, stdout: {out}, stderr: {err}'


def test_with_priv_key_with_gaslimit_no_daemon():
    env = os.environ.copy()
    env['CONSIDER_WITHDRAWALS_FROM_EPOCH'] = '32'
    assert env.get('MEMBER_PRIV_KEY'), 'MEMBER_PRIV_KEY must be set in environment variables'
    assert 'DAEMON' not in env, 'DAEMON must not be set in environment variables'
    custom_gas = 42
    env['GAS_LIMIT'] = f'{custom_gas}'
    expected_prompt = "Should we send this TX? [y/n]: "
    with subprocess.Popen(
        ['python3', '-u', './app/oracle.py'],
        bufsize=0,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    ) as proc:
        lines = get_log_lines(proc, n_lines=100, stop_on_substring=expected_prompt)
        match = [i for i, line in enumerate(lines) if regex.match(r'.* Connected to .* network', line)]
        assert len(match) == 1, f'bad output {lines}'
        index = match[0]
        assert lines[index + 1].endswith('Injecting PoA compatibility middleware')
        assert lines[index + 2].endswith('MEMBER_PRIV_KEY provided, running in transactable (PRODUCTION) mode')
        assert regex.match(r'.* Member account\: .*', lines[index + 3])
        # expect transaction line to be like
        # Tx data: {
        #   'value': 0, 'gasPrice': 1000000000, 'chainId': 5, 'from': '0xb4124cEB3451635DAcedd11767f004d8a28c6eE7',
        #   'gas': 42, 'to': '0xcD3db5ca818a645359e09543Cc0e5b7bB9593229',
        #   'data': '0x62eeb732000000000000000000000000000000000000000000000000000000000000047400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
        # }
        tx_line = lines[-2]
        prompt_line = lines[-1]
        assert regex.match(r'.*Tx data\: .*', tx_line)
        tx_data_raw = tx_line.split('Tx data: ')[-1]
        tx_data = ast.literal_eval(tx_data_raw)
        assert tx_data['gas'] == custom_gas
        assert expected_prompt in prompt_line
        proc.stdin.write('n\n')
    assert proc.returncode == 0, f'output {lines}'


def test_with_priv_key_no_gaslimit_no_daemon():
    env = os.environ.copy()
    env['CONSIDER_WITHDRAWALS_FROM_EPOCH'] = '32'
    assert env.get('MEMBER_PRIV_KEY'), 'MEMBER_PRIV_KEY must be set in environment variables'
    assert 'DAEMON' not in env, 'DAEMON must not be set in environment variables'
    env.pop('GAS_LIMIT', None)
    expected_prompt = "Should we send this TX? [y/n]: "
    with subprocess.Popen(
        ['python3', '-u', './app/oracle.py'],
        bufsize=0,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    ) as proc:
        lines = get_log_lines(proc, n_lines=100, stop_on_substring=expected_prompt)
        match = [i for i, line in enumerate(lines) if regex.match(r'.* Connected to .* network', line)]
        assert len(match) == 1, f'bad output {lines}'
        index = match[0]
        assert lines[index + 1].endswith('Injecting PoA compatibility middleware')
        assert lines[index + 2].endswith('MEMBER_PRIV_KEY provided, running in transactable (PRODUCTION) mode')
        assert regex.match(r'.* Member account\: .*', lines[index + 3])
        # expect transaction line to be like
        # Tx data: {
        #   'value': 0, 'gasPrice': 1000000000, 'chainId': 5, 'from': '0xb4124cEB3451635DAcedd11767f004d8a28c6eE7',
        #   'gas': 42, 'to': '0xcD3db5ca818a645359e09543Cc0e5b7bB9593229',
        #   'data': '0x62eeb732000000000000000000000000000000000000000000000000000000000000047400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
        # }
        tx_line = lines[-2]
        prompt_line = lines[-1]
        assert regex.match(r'.*Tx data\: .*', tx_line)
        tx_data_raw = tx_line.split('Tx data: ')[-1]
        tx_data = ast.literal_eval(tx_data_raw)
        assert tx_data['gas'] == DEFAULT_GAS_LIMIT
        assert expected_prompt in prompt_line
        proc.stdin.write('n\n')
    assert proc.returncode == 0, f'output {lines}'


def test_with_priv_key_with_daemon_no_sleep():
    env = os.environ.copy()
    env['CONSIDER_WITHDRAWALS_FROM_EPOCH'] = '32'
    assert env.get('MEMBER_PRIV_KEY'), 'MEMBER_PRIV_KEY must be set in environment variables'
    assert 'SLEEP' not in env, 'SLEEP must not be set in environment variables'
    env['DAEMON'] = '1'
    env['FORCE_DO_NOT_USE_IN_PRODUCTION'] = '1'
    with subprocess.Popen(
        ['python3', '-u', './app/oracle.py'],
        bufsize=0,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    ) as proc:
        lines = get_log_lines(proc, n_lines=110, timeout=30, stop_on_substring='We are in DAEMON mode. Sleep')
        match = [i for i, line in enumerate(lines) if regex.match(r'.* Connected to .* network', line)]

        assert len(match) == 1, f'bad output {lines}'
        index = match[0]
        assert lines[index + 1].endswith('Injecting PoA compatibility middleware')
        assert lines[index + 2].endswith('MEMBER_PRIV_KEY provided, running in transactable (PRODUCTION) mode')
        assert regex.match(r'.* Member account\: .*', lines[index + 3])
        # expect transaction line to be like
        # Tx data: {
        #   'value': 0, 'gasPrice': 1000000000, 'chainId': 5, 'from': '0xb4124cEB3451635DAcedd11767f004d8a28c6eE7',
        #   'gas': 42, 'to': '0xcD3db5ca818a645359e09543Cc0e5b7bB9593229',
        #   'data': '0x62eeb732000000000000000000000000000000000000000000000000000000000000047400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
        # }
        tx_line = lines[-18]
        sleep_line = lines[-1]
        print(tx_line, sleep_line)
        assert 'TX successful' in tx_line
        assert 'We are in DAEMON mode. Sleep' in sleep_line
        sleep = float(sleep_line.split('Sleep')[-1].split('s and continue')[0])
        assert sleep == DEFAULT_SLEEP
        proc.kill()
        proc.wait()
    assert proc.returncode == -9, f'output {lines}'


def test_with_priv_key_with_daemon_with_sleep():
    env = os.environ.copy()
    env['CONSIDER_WITHDRAWALS_FROM_EPOCH'] = '32'
    assert env.get('MEMBER_PRIV_KEY'), 'MEMBER_PRIV_KEY must be set in environment variables'
    env['DAEMON'] = '1'
    env['FORCE_DO_NOT_USE_IN_PRODUCTION'] = '1'
    custom_sleep = 42
    env['SLEEP'] = f'{custom_sleep}'
    with subprocess.Popen(
        ['python3', '-u', './app/oracle.py'],
        bufsize=0,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    ) as proc:
        lines = get_log_lines(proc, n_lines=100, timeout=30, stop_on_substring='We are in DAEMON mode. Sleep')
        match = [i for i, line in enumerate(lines) if regex.match(r'.* Connected to .* network', line)]
        assert len(match) == 1, f'bad output {lines}'
        index = match[0]
        assert lines[index + 1].endswith('Injecting PoA compatibility middleware')
        assert lines[index + 2].endswith('MEMBER_PRIV_KEY provided, running in transactable (PRODUCTION) mode')
        assert regex.match(r'.* Member account\: .*', lines[index + 3])
        # expect transaction line to be like
        # Tx data: {
        #   'value': 0, 'gasPrice': 1000000000, 'chainId': 5, 'from': '0xb4124cEB3451635DAcedd11767f004d8a28c6eE7',
        #   'gas': 42, 'to': '0xcD3db5ca818a645359e09543Cc0e5b7bB9593229',
        #   'data': '0x62eeb732000000000000000000000000000000000000000000000000000000000000047400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
        # }
        tx_line = lines[-18]
        sleep_line = lines[-1]
        assert 'TX successful' in tx_line
        assert 'We are in DAEMON mode. Sleep' in sleep_line
        sleep = float(sleep_line.split('Sleep')[-1].split('s and continue')[0])
        assert sleep == custom_sleep
        proc.kill()
        proc.wait()
    assert proc.returncode == -9, f'output {lines}'
