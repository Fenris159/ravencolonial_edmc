# RavenColonial EDMC Plugin Action Map

This map traces journal/CAPI actions to the plugin's current RavenColonial API calls.

## Requested actions -> endpoints

### 1) Cargo delivered to fleet/squadron carrier

- **Journal events:** `MarketSell`, `CargoTransfer` (to carrier branch), and squadron `Cargo` resync diff path.
- **Primary endpoint used:** `PATCH /api/fc/{marketId}/cargo`
  - Called via `supply_fc()` with signed deltas (`+count` when cargo moves into FC, `-count` when out).
- **Related reads/baseline endpoints:**
  - `GET /api/cmdr/{cmdr}/fc/all` on init to load linked FCs and server cargo baseline.
  - `GET /api/fc/{marketId}` exists for market reconciliation path, but the trigger is currently disabled in `load.py`.
- **Notes:**
  - Squadron FCs intentionally skip one transfer branch and rely on commander cargo diff sync to produce the FC delta (still patched through `PATCH /api/fc/{marketId}/cargo`).

### 2) Cargo transferred into player ship cargo

- **Journal events:** `MarketBuy`, `CargoTransfer` (to ship branch).
- **Endpoint used for FC state impact:** `PATCH /api/fc/{marketId}/cargo`
  - Applies negative deltas to FC when cargo goes into player ship (`-count`).
- **No direct "player cargo transfer" endpoint** is called for this transfer event itself.
- **Related player hold snapshot endpoint (separate feature):**
  - `POST /api/cmdr/currentShip` is sent on `Cargo`/`Loadout`/`SetUserShipName` when enabled (not a transfer transaction endpoint).

### 3) Cargo transferred into port/settlement/build/construction site

- **Construction delivery events:** `ColonisationContribution` (commander attribution).
- **Endpoint used:** `POST /api/project/{buildId}/contribute/{cmdr}`
  - Called via `contribute_cargo()` with delivered commodity deltas.
  - **History only** — does not change project remaining need.
- **`CargoDepot` (`SubType == Deliver`):** does **not** call `/contribute` or `/supply`. Remaining need is updated when the resulting **`ColonisationConstructionDepot`** journal line arrives (see §4).
- **Not used:** `POST /api/project/{buildId}/supply/{cmdr}` (web “deliver to site”; subtracts need then contributes — would double-apply when depot PATCH is already in use).

### 4) Required values updated from build site market/depot state

- **Journal event:** `ColonisationConstructionDepot`.
- **Flow:** shared `build_depot_project_fields()` derives `remaining_need` (`RequiredAmount − ProvidedAmount`, ≥ 0), `maxNeed`, and the full depot snapshot.
- **Endpoints used:**
  - `GET /api/system/{id64}/{marketId}` to resolve active project / `buildId` (calls `get_project(..., use_location_cache=False)` when depot totals **change**, so PATCH does not rely on the short positive TTL cache).
  - **`PATCH /api/project/{buildId}`** with payload:
    - `buildId`
    - `colonisationConstructionDepot` (full journal line — authoritative)
    - `commodities` (remaining need map)
    - `maxNeed` (sum of required amounts)
- **Trigger condition:** only when depot-needed state changes from last snapshot.
- **After create / link:** `PUT /api/project` includes the same depot fields; a follow-up PATCH is **skipped** when PUT already sent the live remaining-need snapshot (fresh dock).
- **Phantom commodity rows:** when a project response already in hand (PUT/PATCH/location GET) includes negative commodity keys (server template slots at `-1`), opportunistic PATCH zeros those keys — no extra hunt GET.

### 5) Dock-slot project probe / Link Build Site / Create Build Project

- **UI actions:** Main-tab button state (**Open Build Page** vs **Create** / **Link**), **Create Build Project** (scratch dialog), and **Link Build Site** all depend on “is there already a project at this dock?” logic in `check_existing_project`, which ultimately calls **`GET /api/system/{id64}/{marketId}`** via `RavencolonialAPIClient.get_project` (same URL the journal paths use).
- **Not used for that dock-slot answer:** merging **`GET /api/v2/system/{id64}/sites`** into the location result. Plan sites **`/sites`** is still used to **populate the plan-site dropdown** and for the **Link worker’s** live row check below; it is **not** fused into “existing project at `marketId`” for the main-tab probe anymore.
- **Plan-site row refresh (↻, UI only):** background worker runs **`GET /api/v2/system/{id64}/architect`** then **`GET /api/v2/system/{id64}/sites`** (same order for every commander who has a loaded commander string).
  - **Architect match:** parsed architect name from the first response equals EDMC’s commander (`cmdr_name` then `cmdr_snapshot`, case-insensitive). Double-encoded JSON strings (e.g. `"Fenris Nihilus"` with literal quotes) are unwrapped before compare. The UI caches **all** rows with **`status == "plan"`** and sets **`plan_sites_allow_create_new`** so the dropdown also offers **Create New** (opens the scratch **Create Build Project** dialog).
  - **Non-architect:** same **`/sites`** payload, but the cached list is **only** **`plan`** rows whose **`buildType`** passes **`orbital_allowlist.is_orbital_build_type`** in the plugin. **`plan_sites_allow_create_new`** is false (**Create New** hidden). This supports a **docked pilot** choosing an **orbital** plan site the **system architect pre-planned on Ravencolonial**—including when the architect has **moved the site forward remotely** on the site—then using **Link Build Site** to run **`PUT /api/project`** and bind this dock. It is **not** the same as “only the architect may use the plugin”: surface-only **`plan`** rows are simply excluded from this dropdown so they are not linked from an orbital construction megaship by mistake.
  - **Empty non-architect list:** UI shows **No Orbitals** (disabled combobox value), not a legacy “not architect” block on the whole row.
- **`PUT /api/project` (Link Build Site):** Same link payload for both modes; **`architectName`** is always the EDMC commander at the dock. **`buildName`** is the normalized dock station name (not the plan codename). Body includes **`bodyNum`** / **`bodyName`** from the plan row (via **`GET .../bodies`** name lookup when needed), **`commodities`**, **`maxNeed`**, and **`colonisationConstructionDepot`** from the journal (same as scratch **Create Project**). **Architects** may have selected **any** `plan` row type (orbital, surface port, station, etc.) to match where they are docked; **non-architects** were only offered **orbital** `plan` rows in the refresh UI, so their selection set is narrower by design, not a different API.
- **Link Build Site** still performs its **own** live **`GET .../sites`** before **`PUT`** (not a reuse of the refresh response). On success, the linked **`plan`** row is removed from the **Select Plan Site** dropdown immediately.
- **Response handling is normalized (important):**
  - `resolve_build_id` treats `buildId`, `BuildId`, and `build_id` as the same signal.
  - `active_project_from_system_location_json` unwraps common wrapper keys (`data`, `project`, `result`, …) and JSON-in-string bodies.
  - If the payload is a string or ProblemDetails-like body containing “no active project” → no active project.
  - If HTTP status is `404` but `completed_project_hint_from_system_location_json` matches (for example `complete: true`, or `status` / `buildStatus` indicating complete/finished) → treat as an existing completed record (blocks duplicate create/link the same way an active `buildId` would).
- **Throttling (main tab + non-click probes):** `check_existing_project(..., force=False)` uses a short positive TTL on successful `get_project(..., use_location_cache=True)` hits, and after one “no `buildId`” outcome for `(systemAddress, marketId)` it **skips further `GET /api/system/...` until** `invalidate_project_location_cache()` **or** `check_existing_project(..., force=True)`. The latter runs **immediately before** opening the scratch **Create** dialog or starting the **Link** worker, so a build that appeared while still docked is re-fetched on the network.
- **Additional anti-duplicate guard — Link Build Site worker only (before `PUT /api/project`):**
  - Live `GET /api/v2/system/{id64}/sites`; if the selected `systemSiteId` row is no longer `plan` (for example `build` or `complete`), the worker stops and does **not** `PUT`.
  - Live `GET /api/system/{id64}/{marketId}` again inside the worker; if an active (or completion-hint) project is present, the worker stops.
- **Scratch Create path:** after the click-time `force=True` probe, **`PUT /api/project`** from the dialog — there is **no** `/sites` “still plan” gate on that path (the dialog is scratch create or pre-planned site fields from its own UI).
- **Create / link endpoint when allowed:** `PUT /api/project` (OpenAPI; body includes `marketId`, `systemAddress`, `buildType`, optional `systemSiteId`, `buildName`, depot snapshot, …).

## Need vs history (construction routes)

| Route | Plugin uses? | Remaining need | Commander history |
|---|---|---|---|
| **`PATCH /api/project/{buildId}`** + depot | **Yes** — `ColonisationConstructionDepot` | Sets from journal | — |
| **`PUT /api/project`** + depot | **Yes** — create / link | Initial need map | — |
| **`POST …/contribute/{cmdr}`** | **Yes** — `ColonisationContribution` only | **No change** | Adds ledger rows |
| **`POST …/supply/{cmdr}`** | **No** | Would subtract + contribute | Would add (bundled) |
| **`POST /api/project/{buildId}`** (legacy) | **No** (v1.6.7+) | SrvSurvey path; superseded by PATCH for depot | — |

See [RavenColonial_API_Reference.md — Construction: remaining need vs delivery history](RavenColonial_API_Reference.md#construction-remaining-need-vs-delivery-history) for server-side semantics.

## FC metadata and placement (current behavior)

- Plugin currently **does not call**:
  - `PATCH /api/fc/{marketId}` (FC metadata)
  - `POST /api/fc/{nameOrNum}/location/{system}` (placement/location)
  - `POST /api/fc/{nameOrNum}/spansh`
- FC sync in plugin is cargo-oriented (`/fc/{marketId}/cargo`) plus linked-FC discovery (`/cmdr/{cmdr}/fc/all`).

## Commander project listing endpoint

- The helper `get_commander_projects(cmdr)` is now aligned to:
  - `GET /api/cmdr/{cmdr}/active`
- This replaces the broader:
  - `GET /api/cmdr/{cmdr}`
- **Current usage status in plugin:** helper exists but is not currently wired into the main UI/event flow; active build resolution in the main tab still uses:
  - `GET /api/system/{id64}/{marketId}` for “existing project at current dock location” via `check_existing_project` / `get_project`, with client-side normalization for **200** / **404** payload variants, wrapper JSON, and `resolve_build_id`-style `buildId` keys (see `api/client.py`).

## Does plugin check server commodity needs and keep updating while items move?

### Fleet/squadron carriers

- **Yes, partially.**
  - It checks profile-linked FC records on startup via `GET /api/cmdr/{cmdr}/fc/all`.
  - It also reads `GET /api/cmdr/{cmdr}/active` and adds every active project `linkedFC[].marketId` to the same PATCH-eligible marketId set. Duplicate marketIds are collapsed to one entry, so a profile-linked FC that is also project-linked does not double-PATCH.
  - It updates FC cargo live with `PATCH /api/fc/{marketId}/cargo` as journal events move cargo in/out.
- **But not full continuous reconciliation by polling.**
  - Market reconciliation path (`handle_market_event` -> `_update_fc_from_market` using `GET /api/fc/{marketId}` + `POST /api/fc/{marketId}/cargo`) exists but is currently disabled in the main event router.

### Construction sites

- **Yes for project needed values from journal depot state, not by polling server market needs.**
  - On each `ColonisationConstructionDepot` change it recalculates needed commodities and **`PATCH`**es project totals with the full depot snapshot.
  - **`ColonisationContribution`** posts attribution via **`POST /api/project/{buildId}/contribute/{cmdr}`** only (no `/supply`).
- **No server-side "needs polling" loop** is present.

## Compact flow map

1. **Dock/init**
   - `GET /api/cmdr/{cmdr}/fc/all` (load linked FCs + cargo baseline)
   - `GET /api/cmdr/{cmdr}/active` (add active project `linkedFC` marketIds to FC PATCH eligibility)
2. **FC cargo movement**
   - `MarketSell`/`MarketBuy`/`CargoTransfer`/squadron cargo-resync -> `PATCH /api/fc/{marketId}/cargo`
3. **Construction delivery attribution**
   - `ColonisationContribution` -> `POST /api/project/{buildId}/contribute/{cmdr}` (history only)
4. **Construction needs refresh**
   - `ColonisationConstructionDepot` totals changed -> uncached `GET /api/system/{id64}/{marketId}` -> **`PATCH /api/project/{buildId}`** (`colonisationConstructionDepot`, `commodities`, `maxNeed`)
5. **Plan-site combobox refresh (↻, UI only)**
   - `GET /api/v2/system/{id64}/architect` then `GET /api/v2/system/{id64}/sites`
   - **Architect** (name match): cache all `plan` rows + **Create New** in UI (`plan_sites_allow_create_new`)
   - **Non-architect:** cache `plan` rows with orbital `buildType` only (`orbital_allowlist.is_orbital_build_type`); no **Create New**; empty list → **No Orbitals** — supports linking a **pre-planned orbital** the system architect may have **advanced remotely** on the site before the docked pilot uses **Link Build Site**
6. **Dock-slot project probe (main tab + click preflight)**
   - `check_existing_project` -> `GET /api/system/{id64}/{marketId}` (normalized **200**/**404** payloads, `buildId` spelling / wrappers); positive TTL on cached hits; negative freeze after “empty” until invalidation or `force=True` before **Create** / **Link**
7. **Link Build Site worker (after UI preflight)**
   - `GET /api/v2/system/{id64}/sites` (selected row still `plan`) -> `GET /api/system/{id64}/{marketId}` again -> `PUT /api/project` (depot snapshot + normalized `buildName`) if allowed
8. **Not currently wired**
   - `POST /api/project/{buildId}/supply/{cmdr}` (deliver-to-site — subtract + contribute)
   - `POST /api/project/{buildId}` for depot sync (legacy; replaced by PATCH in v1.6.7+)
   - FC metadata/location routes (`PATCH /api/fc/{marketId}`, `POST /api/fc/{nameOrNum}/location/{system}`)
   - Commander-project list helper output (`GET /api/cmdr/{cmdr}/active`) is consumed for FC PATCH eligibility, but not for current main-tab build resolution
