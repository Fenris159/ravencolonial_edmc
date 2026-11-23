# Ravencolonial EDMC v1.8.6

## Carrier cargo tracking

- Prevent squadron-carrier market sales and purchases from being counted twice when EDMC reads a newer Cargo.json ahead of queued journal events. Keep explicit transfers and separate bank movements distinct.
- Publish current ship cargo after market trades on both carrier types and ordinary stations. Accept valid state-backed sparse ship views while bank inference waits for complete inventory. Validate matching main-ship cargo files and retain the last trusted hold when incremental state is ambiguous.
- Preserve the difference between unloaded startup inventory and a genuinely empty hold. Keep SRV, fighter, limpet-service, and other ship-only changes out of carrier deliveries.
- Use one pending inventory window for uncertain bank attribution. Same-second ambiguity waits for fresh complete inventory; unresolved startup or manual-correction history waits for a verified carrier sync or manual correction. Known journal movements remain ordered and recoverable. This favors a delayed update over a guessed balance.
- Preserve unresolved evidence across commander changes and restart. Manual corrections and full carrier syncs cover the evidence captured when they are reserved; later movements survive delayed acknowledgements. Keep that coverage across later ship snapshots and trades, and consume excluded ship activity when rebasing in carrier stealth mode.
- Reserve queued withdrawals and verify confirmed stock before HTTP. Unknown or insufficient stock leaves the delivery pending. Recovery refreshes refused withdrawals after failed or stale baseline reads, then resumes ordered deliveries.
- Retain durable transaction identities, uncertain HTTP outcomes, failed checkpoints, commander eligibility, and full-save ordering safeguards. Returning to a previous ship amount still publishes correctly when another update is queued.

Previously incorrect carrier balances still need a one-time manual correction.
