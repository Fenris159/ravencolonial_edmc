# Ravencolonial EDMC v1.8.4

## Release highlights

Version 1.8.4 fixes commander switching without restarting EDMC and improves cargo tracking for regular and squadron Fleet Carriers. It also improves recovery after network or storage failures, keeps manual manifest corrections in order, and fixes related construction tracker and updater issues.

## Commander switching

- Project and carrier links refresh in the background when the active commander changes, including session startup events.
- Transfers observed while links are loading remain attached to their original commander. Delayed responses cannot grant the next commander the previous commander's carrier links.
- Open manifest editors close when commanders change. Reopening an editor during discovery fills its carrier list when discovery finishes, and old save callbacks cannot alter a newer commander's form.

## Carrier cargo tracking

- Regular and squadron carriers track explicit cargo transfers and market trades by carrier market ID. Squadron banks also recover movements reported only through ship inventory snapshots, without counting the same movement twice.
- SRV and fighter activity, mismatched market trades, and maintenance limpet purchases or sales are excluded from inferred bank transfers.
- Failed writes retain recovery evidence across commander changes and restarts. The plugin checks the result before retrying, preventing a lost reply from duplicating a delivery. Proven connection-establishment failures can recover when connectivity returns.
- Full cargo snapshots explicitly remove commodities whose amount has fallen to zero. Snapshot coverage and pending movements stay ordered across commander sessions, including movements arriving during a baseline read.
- Manual manifest corrections participate in recovery and preserve their order relative to journal updates. Delayed editor callbacks retain the latest confirmed stock, and newer manual saves take precedence over older requests still completing their reads.
- Recovered manual saves refresh the correct carrier even after switching carriers. Recovery keeps later edits and commodity removals, and stops when a preflight read observes changed stock.
- Completed movements retain freshness evidence so delayed Frontier CAPI data cannot overwrite newer acknowledged cargo. An observed empty manifest is valid zero stock; missing manifests and unknown inventory remain `sync`.

## Other fixes

- Construction depot updates remain tied to the correct build and visit, and authoritative journal totals can correct server drift after re-docking or a late reply.
- Failed or malformed commander-link responses honor retry backoff rather than retrying on every journal event.
- Cancelled carrier jump callbacks cannot advance a newer jump.
- Update validation checks the complete runtime package before replacing the working plugin. Save, dialog, and updater failures reach their recovery handlers.

## Validation

The full local suite passed with **445 passed, 1 skipped**. The skip requires an external EDMCModernOverlay installation. Repository-wide Flake8 reported **0 findings**. Behavior regressions cover commander changes, both carrier types, delayed reads and saves, failed writes, restarts, storage failures, and construction depot drift. Independent Standards and Spec reviews found no remaining material issues. Live in-game validation has not been performed.

## Installation

The stable release is available to normal in-app update checks. For manual installation, download `RavenColonial_EDMC-v1.8.4.zip` from [the v1.8.4 release](https://github.com/Fenris159/ravencolonial_edmc/releases/tag/v1.8.4), extract the `RavenColonial_EDMC` folder into EDMC's plugins directory, and restart EDMC. Pending carrier recovery data remains in EDMC's user-data directory when the plugin folder is replaced.
