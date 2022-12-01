
def update_steth_price_oracle_data():
    logging.info('Check StETH Price Oracle state')
    try:
        block_number = w3.eth.getBlock('latest').number - steth_price_oracle_block_number_shift
        oracle_price = steth_price_oracle.functions.stethPrice().call()
        pool_price = steth_curve_pool.functions.get_dy(1, 0, 10**18).call(block_identifier=block_number)
        percentage_diff = 100 * abs(1 - oracle_price / pool_price)
        logging.info(
            f'StETH stats: (pool price - {pool_price / 1e18:.6f}, oracle price - {oracle_price / 1e18:.6f}, difference - {percentage_diff:.2f}%)'
        )

        metrics_exporter_state.set_steth_pool_metrics(oracle_price, pool_price)

        proof_params = steth_price_oracle.functions.getProofParams().call()

        # proof_params[-1] contains priceUpdateThreshold value in basis points: 10000 BP equal to 100%, 100 BP to 1%.
        price_update_threshold = proof_params[-1] / 100
        is_state_actual = percentage_diff < price_update_threshold

        if is_state_actual:
            logging.info(
                f'StETH Price Oracle state valid (prices difference < {price_update_threshold:.2f}%). No update required.'
            )
            return

        if dry_run:
            logging.warning("Running in dry run mode. New state will not be submitted.")
            return

        logging.info(
            f'StETH Price Oracle state outdated (prices difference >= {price_update_threshold:.2f}%). Submiting new one...'
        )

        header_blob, proofs_blob = encode_proof_data(provider, block_number, proof_params)

        max_fee_per_gas, max_priority_fee_per_gas = _get_tx_gas_params()
        tx = steth_price_oracle.functions.submitState(header_blob, proofs_blob).buildTransaction(
            {
                'gas': 2_000_000,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee_per_gas,
            }
        )

        w3.eth.call(tx)
        logging.info('Calling tx locally succeeded.')
        sign_and_send_tx(tx)
    except SolidityError as sl:
        metrics_exporter_state.exceptionsCount.inc()
        logging.error(f'Tx call failed : {sl}')
    except ValueError as exc:
        (args,) = exc.args
        if isinstance(args, dict) and args["code"] == -32000:
            raise
        else:
            metrics_exporter_state.exceptionsCount.inc()
            logging.exception(exc)
    except TimeExhausted:
        raise
    except Exception as exc:
        metrics_exporter_state.exceptionsCount.inc()
        logging.exception(f'Unexpected exception. {type(exc)}')
