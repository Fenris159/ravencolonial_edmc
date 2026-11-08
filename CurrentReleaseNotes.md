# Ravencolonial EDMC v1.8.5

## Squadron carrier cargo correction

- Fix a startup regression that could subtract cargo already aboard your ship from a squadron carrier, then cancel out a real deposit. Learning the initial ship inventory now establishes a baseline without reporting a transfer.
- Preserve confirmed empty holds so later squadron-bank withdrawals and deposits continue to update carrier stock.
- Keep incomplete inventory snapshots unknown, discard inventory readiness when a new game or ship starts, and count explicit transfers before the initial snapshot exactly once.
- Treat a zero-count cargo journal as an empty hold even when EDMC's cached cargo is stale.

## Validation

Regression replays cover the reported 1,383 + 1,323 = 2,706 steel deposit, unloaded versus confirmed empty inventory, sparse snapshots, session changes, stale cached state, and early explicit transfers.
