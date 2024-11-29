How to run e2e tests with anvil fork

1. Install anvil
2. Setup next variables
```
LIDO_LOCATOR_ADDRESS=0xC1d0b3DE6792Bf6b4b37EccdcC24e45978Cfd2Eb
KEYS_API_URI=https://keys-api.lido.fi/
ANVIL_PATH=/Users/user/.foundry/bin/
CONSENSUS_CLIENT_URI=...
EXECUTION_CLIENT_URI=...
```
3. pytest run -m e2e
