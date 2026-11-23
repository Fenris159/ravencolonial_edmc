# Ravencolonial EDMC v1.8.6

## Carrier cargo tracking

- Prevent squadron-carrier market sales and purchases from being counted twice when EDMC reads a newer `Cargo.json` ahead of queued journal events. Keep explicit transfers and separate bank movements distinct.
- Publish current ship cargo after market trades on both carrier types and ordinary stations, including consecutive same-second station trades without a matching `Cargo.json`. Accept valid state-backed sparse ship views while bank inference waits for complete inventory, sum duplicate commodity stacks against `Count`, suppress duplicate sends, recheck ship-cargo stealth right before sending, and clear duplicate certainty after failed publishes.
- Preserve the difference between unloaded startup inventory and a genuinely empty hold. Keep SRV, fighter, limpet-service, and other ship-only changes out of carrier deliveries, and avoid inferring bank withdrawals from read-ahead files on ship-only events.
- Use one pending inventory window for uncertain bank attribution. Same-second ambiguity waits for fresh complete inventory; unresolved startup or manual-correction history waits for a verified carrier sync or manual correction. Keep funds-window inventory consistent when `Cargo.json` advances on ship-only callbacks, and rebuild optimistic carrier stock from confirmed stock when cancelling unattempted inferred deposits.
- Preserve unresolved evidence, manual-correction barriers, provenance-aware bank coverage, and already-credited unknown-origin deltas across commander switches, eligibility revocations/relinks, and restarts. Manual corrections and full carrier syncs cover the evidence captured when reserved; later movements survive delayed acknowledgements.
- Reserve queued withdrawals and verify confirmed stock before HTTP. Unknown or insufficient stock leaves the delivery pending. Recovery refreshes refused withdrawals after failed or stale baseline reads, then resumes ordered deliveries.
- Retain durable transaction identities, uncertain HTTP outcomes, failed checkpoints, commander eligibility, and full-save ordering safeguards.

## Fleet Carrier market sync, link refresh, & API parity

- Sync linked Fleet Carrier market commodity stocks from `Market.json` via partial cargo updates, ordered behind prior signed trades, full replacements, pending dock baselines, and overlapping held frames while allowing later dependent frames to fund and retry cleanly.
- Dynamically refresh commander and active-project carrier links when docking at a newly linked or uncached carrier, retaining deferred trades and `Market` snapshots across transient discovery outages and commander switches while revoking unlinked or completed carriers and isolating overlay/depot link updates per commander.
- Enforce chronological freshness across initialization replay, CAPI snapshots, partial `Market.json` syncs, and deferred trades so older snapshots cannot overwrite newer stock and covered deferred trades are not double-applied. Wake active handlers when deferred `Market` callbacks are discarded and defer nested baseline UI refreshes outside locks.
- Sync `StartUp` / live EDMC dock state (`IsDocked` / `Docked`), default the RavenColonial API base URL to `https://ravencolonial.net`, and trim configured API URLs and `rcc-key` credentials.

Previously incorrect carrier balances still need a one-time manual correction.
