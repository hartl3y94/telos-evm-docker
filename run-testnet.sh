#!/bin/bash

tevmc clean
tevmc pull --headless

tevmc config \
            --hyperion-cfg-path=docker/hyperion/config/chains/telos-testnet.config.json \
            --indexer-start-on=136229794 \
            --index-only-evm

tevmc build --headless

tevmc up \
    --loglevel=info \
    --chain-name=telos-testnet \
    --snapshot=/root/snapshots/snapshot-testnet-20211020-blknum-136229794.bin

tevmc wait-init

printf '\n\n\nTEVM testnet up, run `tevmc down` to stop.\n\n\n'
