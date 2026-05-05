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

- **Construction delivery events:** `CargoDepot` (`SubType == Deliver`) and `ColonisationContribution`.
- **Endpoint used today:** `POST /api/project/{buildId}/contribute/{cmdr}`
  - Called via `contribute_cargo()` with delivered commodity deltas.
- **Not used today for this path:** `POST /api/project/{buildId}/supply/{cmdr}` ("deliver to site" route used by web client).

### 4) Required values updated from build site market/depot state

- **Journal event:** `ColonisationConstructionDepot`.
- **Flow:** compute `still_needed = RequiredAmount - ProvidedAmount` per commodity; compute `maxNeed`.
- **Endpoints used:**
  - `GET /api/system/{id64}/{marketId}` to resolve active project/buildId.
  - `POST /api/project/{buildId}` with payload:
    - `buildId`
    - `commodities` (current needed map)
    - `maxNeed` (sum of required amounts)
- **Trigger condition:** only when depot-needed state changes from last snapshot.

## "Deliver to site" vs contribute (current behavior)

- Plugin currently writes **construction cargo deliveries** using:
  - `POST /api/project/{buildId}/contribute/{cmdr}`
- Plugin currently **does not call**:
  - `POST /api/project/{buildId}/supply/{cmdr}`
  - `PUT /api/project/{buildId}/supply/{cmdr}`
- So if backend treats supply/deliver-to-site separately from contribute, web and plugin can diverge on those views.

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
  - `GET /api/system/{id64}/{marketId}` for "existing project at current dock location".

## Does plugin check server commodity needs and keep updating while items move?

### Fleet/squadron carriers

- **Yes, partially.**
  - It checks server-linked FC records on startup via `GET /api/cmdr/{cmdr}/fc/all`.
  - It updates FC cargo live with `PATCH /api/fc/{marketId}/cargo` as journal events move cargo in/out.
- **But not full continuous reconciliation by polling.**
  - Market reconciliation path (`handle_market_event` -> `_update_fc_from_market` using `GET /api/fc/{marketId}` + `POST /api/fc/{marketId}/cargo`) exists but is currently disabled in the main event router.

### Construction sites

- **Yes for project needed values from journal depot state, not by polling server market needs.**
  - On each `ColonisationConstructionDepot` change it recalculates needed commodities and updates project totals via `POST /api/project/{buildId}`.
  - Delivery transactions are posted as contributions via `POST /api/project/{buildId}/contribute/{cmdr}`.
- **No server-side "needs polling" loop** is present.

## Compact flow map

1. **Dock/init**
   - `GET /api/cmdr/{cmdr}/fc/all` (load linked FCs + cargo baseline)
2. **FC cargo movement**
   - `MarketSell`/`MarketBuy`/`CargoTransfer`/squadron cargo-resync -> `PATCH /api/fc/{marketId}/cargo`
3. **Construction delivery**
   - `CargoDepot` deliver or `ColonisationContribution` -> `POST /api/project/{buildId}/contribute/{cmdr}`
4. **Construction needs refresh**
   - `ColonisationConstructionDepot` changed -> `GET /api/system/{id64}/{marketId}` -> `POST /api/project/{buildId}` (`commodities`, `maxNeed`)
5. **Not currently wired**
   - `POST /api/project/{buildId}/supply/{cmdr}` (deliver-to-site)
   - FC metadata/location routes (`PATCH /api/fc/{marketId}`, `POST /api/fc/{nameOrNum}/location/{system}`)
   - Commander-project list helper output (`GET /api/cmdr/{cmdr}/active`) is available but not yet consumed by current main-tab flow
