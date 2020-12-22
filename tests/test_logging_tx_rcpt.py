import logging
import pickle
from app.log import print_tx_receipt


def test_print_tx_receipt_success(caplog):
    tx_rcpt = pickle.load( open("tests/test_logging_tx_rcpt_dump.p", "rb") )
    caplog.set_level(logging.INFO)
    print_tx_receipt(tx_rcpt)
    assert "Tx status: 1 (Success)" in caplog.text
    assert "Tx mined in block: 709" in caplog.text
    assert "Tx gas used: 270645" in caplog.text
    assert "Tx Logs: 6" in caplog.text
