# Ravencolonial EDMC v1.8.6

## Carrier market cargo accounting

- Prevent squadron-carrier sales being counted twice when inventory arrives ahead of the matching market event. Keep separate bank movements, market trades, and explicit transfers distinct.
- Publish updated ship cargo after market purchases and sales on both carrier types and ordinary stations without waiting for another inventory event.
- Prefer complete main-ship Cargo.json matching the trade over EDMC cargo that has already been adjusted twice. Ignore unrelated or invalid files, and retain validated cargo when a same-second fallback is ambiguous.
- Keep unloaded startup inventory unknown until a complete hold is available. Exclude limpet service transactions and other known ship-only changes from carrier deliveries.
- Preserve unresolved inventory evidence across restarts and commander changes. Ambiguous startup history waits for a verified full carrier sync or manual correction instead of guessing a balance.
- Prevent late inventory from replaying deferred deliveries after a manual carrier correction.

Previously incorrect carrier balances still need a one-time manual correction.
