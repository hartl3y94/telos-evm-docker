#!/usr/bin/env python3

from pathlib import Path
from hashlib import sha256

import pytest

from leap.protocol import Asset
from leap.errors import TransactionPushError, ChainAPIError

from web3 import Account

from tevmc.cmdline.build import perform_config_build


ZERO_SHA = '0' * int((256 / 8) * 2)

test_account_name = 'testcontract'

test_contracts_dir = Path('tests/contracts')
test_contracts_dir_guest = Path('/opt/eosio/bin/testcontracts')

base_path = test_contracts_dir / 'testcontract/base/testcontract.wasm'
var1_path = test_contracts_dir / 'testcontract/variations/testcontract.var1.wasm'
var2_path = test_contracts_dir / 'testcontract/variations/testcontract.var2.wasm'
var3_path = test_contracts_dir / 'testcontract/variations/testcontract.var3.wasm'

base_wasm = base_path.read_bytes()
var1_wasm = var1_path.read_bytes()
var2_wasm = var2_path.read_bytes()
var3_wasm = var3_path.read_bytes()

base_hash = sha256(base_wasm).hexdigest()
var1_hash = sha256(var1_wasm).hexdigest()
var2_hash = sha256(var1_wasm).hexdigest()
var3_hash = sha256(var1_wasm).hexdigest()


def test_subst_api(subst_testing_nodeos):
    # start nodeos with no subst conf or contract deployed
    tevmc = subst_testing_nodeos

    # no base contract deployed
    with pytest.raises(ChainAPIError):
        tevmc.cleos.get_account(test_account_name)

    # no substitutions yet
    subst_status = tevmc.cleos.subst_status()
    assert len(subst_status['rows']) == 0

    # register new substitution, no actual contract deployed yet
    upsert_result = tevmc.cleos.subst_upsert('testcontract', 0, var1_wasm)
    assert upsert_result['account'] == test_account_name
    assert upsert_result['from_block'] == 0
    assert upsert_result['original_hash'] == ZERO_SHA
    assert upsert_result['substitution_hash'] == var1_hash

    # assert status api shows it
    subst_status = tevmc.cleos.subst_status()
    assert len(subst_status['rows']) == 1

    # any other metadata altering call apart from remove should fail now
    with pytest.raises(ChainAPIError):
        tevmc.cleos.subst_activate(test_account_name)

    with pytest.raises(ChainAPIError):
        tevmc.cleos.subst_deactivate(test_account_name)


def test_subst_change(subst_testing_nodeos_testcontract):
    tevmc = subst_testing_nodeos_testcontract

    def testcontract_print_action(msg: str = 'hello world!', cancel: bool = False) -> str:
        '''print action on testcontract will just print the message with a header
        that is defined by a macro, depending on version of wasm applied the header
        will change, this function will call the action to print a message and return
        a tuple with:
            0 - header
            1 - full console output
        '''
        try:
            res = tevmc.cleos.push_action(
                'testcontract', 'print', [msg, cancel], 'testcontract', retries=1
            )
            console = res['processed']['action_traces'][0]['console']

        except TransactionPushError as err:
            assert cancel
            console = err.pending_output

        header = console.replace(': ' + msg, '')

        return header, console

    def assert_testcontract_has_header(header: str):
        # test cancelled runs subst version
        actual, _ = testcontract_print_action(cancel=True)
        assert actual == header

        tevmc.cleos.wait_blocks(1)

        # test normal runs subst version
        actual, _ = testcontract_print_action()
        assert actual == header

        tevmc.cleos.wait_blocks(1)


    subst_status = tevmc.cleos.subst_status_by_account('testcontract')
    assert subst_status['original_hash'] == ZERO_SHA
    assert subst_status['substitution_hash'] == var1_hash
    assert subst_status['account_metadata_object']['code_hash'] == base_hash

    # breakpoint()

    # case 0: chain has base - we started with subst-by-name with variation 1
    assert_testcontract_has_header('VAR1')

    subst_status = tevmc.cleos.subst_status_by_account('testcontract')
    assert subst_status['original_hash'] == base_hash
    assert subst_status['substitution_hash'] == var1_hash
    assert subst_status['code_object']['actual_code_hash'] == var1_hash

    # case 1: chain as base - ndoeos has subst var1, stop nodeos and change config to variation 2
    tevmc.config['nodeos']['ini']['subst'] = {
        'testcontract': '/opt/eosio/bin/testcontracts/testcontract/variations/testcontract.var2.wasm'
    }

    tevmc._stop_nodeos()

    perform_config_build(tevmc.root_pwd, tevmc.config)

    tevmc.start_nodeos()

    subst_status = tevmc.cleos.subst_status_by_account('testcontract')
    assert subst_status['original_hash'] == base_hash
    assert subst_status['substitution_hash'] == var2_hash
    assert subst_status['account_metadata_object']['code_hash'] == base_hash
    assert subst_status['code_object']['actual_code_hash'] == var1_hash

    assert_testcontract_has_header('VAR2')


@pytest.mark.services('nodeos')
def test_setcode_with_same_hash_subst(tevmc_local):
    tevmc = tevmc_local

    regular_dir = (
        tevmc.docker_wd /
        'leap/contracts/eosio.evm/regular'
    )
    receiptless_dir = (
        tevmc.docker_wd /
        'leap/contracts/eosio.evm/receiptless'
    )

    eth_addr = tevmc.cleos.eth_account_from_name('evmuser1')
    assert eth_addr

    def transfer_and_verify_receipt_happens():
        tevmc.cleos.wait_blocks(1)
        ec, _ = tevmc.cleos.eth_transfer(
            eth_addr,
            Account.create().address,
            '1.0000 TLOS',
            account='evmuser1'
        )
        assert ec == 0

        nodeos_logs = ''
        for msg in tevmc.stream_logs('nodeos', num=3, from_latest=True):
            nodeos_logs += msg
            if 'RCPT' in nodeos_logs:
                break

    # at this point blockchain is running with receiptless on chain
    # and using subst to apply regular

    transfer_and_verify_receipt_happens()

    for _ in range(2):
        tevmc.cleos.deploy_contract_from_path(
            'eosio.evm',
            regular_dir,
            privileged=True,
            create_account=False
        )

        transfer_and_verify_receipt_happens()

        tevmc.cleos.deploy_contract_from_path(
            'eosio.evm',
            receiptless_dir,
            privileged=True,
            create_account=False
        )

        transfer_and_verify_receipt_happens()
