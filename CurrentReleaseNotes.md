# Ravencolonial EDMC v1.8.6

## Carrier market cargo accounting

- Prevent squadron-carrier sales being counted twice when inventory arrives ahead of the matching market event. Keep separate bank movements, market trades, and explicit transfers distinct, including transfers containing multiple commodities.
- Publish updated ship cargo after market purchases and sales on both carrier types and ordinary stations without waiting for another inventory event. Returning to a previously published amount still updates correctly when another cargo update is queued.
- Prefer complete main-ship Cargo.json matching the trade over EDMC cargo that has already been adjusted twice. Ignore unrelated or invalid files, and retain validated cargo when a same-second fallback is ambiguous.
- Keep unloaded startup inventory unknown until a complete hold is available. Exclude limpet service transactions and other known ship-only changes from carrier deliveries.
- Preserve unresolved inventory evidence across restarts and commander changes. Ambiguous startup history waits for a verified full carrier sync or manual correction instead of guessing a balance.
- Keep newer carrier syncs and manual corrections in order, and preserve trades arriving while a full manifest is being saved. Late inventory cannot replay deliveries already covered by a correction.
- Retry failed recovery checkpoints even when no delivery is waiting to send. Preserve delivery identities across restart, retain confirmed evidence, and remove provisional records only after the originating commander lookup proves the carrier is unlinked.

Previously incorrect carrier balances still need a one-time manual correction.
