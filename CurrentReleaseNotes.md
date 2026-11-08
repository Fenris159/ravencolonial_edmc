# Ravencolonial EDMC v1.8.6

## Carrier market cargo accounting

- Prevent squadron-carrier market sales being counted twice when an updated inventory is observed before its matching market event.
- Keep genuine squadron-bank movements and separate market trades distinct, including operations occurring in the same second.
- Update the commander's published ship cargo after market purchases and sales without waiting for another inventory journal event.
- Use a complete main-ship Cargo.json matching the trade when EDMC's cached cargo has already been adjusted twice. Ignore stale, future, malformed, or non-ship files.
- Keep unknown startup inventory unknown after early trades, and preserve explicit trades that happened before the first full inventory was learned.
- Reconcile later transfers and known ship-only mutations already included in a same-second inventory; malformed fractional, boolean, and overflowing file quantities are rejected.
- Retain validated ship cargo when a same-second fallback is ambiguous and resolve provisional bank attribution from the next trustworthy inventory.
- Prevent a late inventory snapshot from undoing a manual carrier correction after a read-ahead market sale.

Previously incorrect carrier balances still need a one-time manual correction. These changes prevent new incorrect adjustments.
