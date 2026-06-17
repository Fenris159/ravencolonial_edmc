# RavenColonial | v1 API Reference

<!-- markdownlint-disable MD012 MD013 MD022 MD024 MD033 MD060 -->

Generated from the OpenAPI 3.1.1 document at `https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net/`.

Spec version: `1.0.0`

## Notes

- This revision adds request-body confidence labels based on the OpenAPI document plus inspected RavenColonialWeb and SrvSurvey client calls.
- Client-confirmed shapes are still not a formal server contract unless they also appear in OpenAPI, but they are stronger than route-name guessing.
- **Construction need vs history:** journal-aware clients (including RavenColonial EDMC v1.6.7+) use **`PATCH`** + **`colonisationConstructionDepot`** for remaining need, **`POST …/contribute`** for commander history only, and avoid **`POST …/supply`** when depot events are available. See [Construction: remaining need vs delivery history](#construction-remaining-need-vs-delivery-history).

- Endpoint descriptions in this document are inferred from routes when the OpenAPI operation has no explicit summary/description.
- Authentication/security requirements are not declared in the OpenAPI document, so this guide marks them as **not specified**.
- Request/response schemas are linked to the schema appendix where possible.

## Base URL

```text
https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net/
```

## Summary

- Total operations documented: **120**
- Endpoints with declared component schemas: **73**
- Endpoints without declared component schemas: **47**
- Component schemas in appendix: **57**

## Quick Links

- [Schema-backed endpoint summary](#schema-backed-endpoint-summary)
- [Schema-backed endpoints](#schema-backed-endpoints)
- [Endpoints without declared component schemas](#endpoints-without-declared-component-schemas)
- [Schema Appendix](#schema-appendix)
- [Method applicability guide (about-page notes)](#method-applicability-guide-about-page-notes)
- [Construction: remaining need vs delivery history](#construction-remaining-need-vs-delivery-history)

## Method Applicability Guide (about-page notes)

This section maps the Raven Colonial `/about` method guidance into practical client usage notes.
It is intended as a quick "which route should I call?" companion to the full endpoint sections below.

### Project methods

| Method | Path | Notes / applicability |
|---|---|---|
| `PUT` | `/api/project` | Create a project. Use for new build creation only. Include `colonisationConstructionDepot` when the client has a journal snapshot. |
| `PATCH` | `/api/project/{buildId}` | **Authoritative remaining need** for journal-aware clients. Send `colonisationConstructionDepot` (full journal line) plus derived `commodities` / `maxNeed` when depot state changes. Merge-style update for other fields (notes, `buildName`, …). |
| `POST` | `/api/project/{buildId}/contribute/{cmdr?}` | **Commander delivery history only** — records attributed cargo in the contribution ledger. Does **not** change project remaining need. Use with `ColonisationContribution` (or equivalent) when the client also PATCHes need from the depot journal. |
| `POST` | `/api/project/{buildId}/supply/{cmdr?}` | **Non-journal “deliver to site”** — subtracts amounts from stored remaining need, then records contribution (bundled). Avoid when the client already PATCHes depot-driven need, or need will be reduced twice. |
| `POST` / `DELETE` | `/api/project/{buildId}/ready` | Add/remove ready flags for listed commodities only; additive semantics for mentioned keys. |
| `POST` | `/api/project/{buildId}/complete` | Mark project complete (irreversible). |

<a id="construction-remaining-need-vs-delivery-history"></a>

#### Construction: remaining need vs delivery history

Build projects separate **how much is still required** from **who delivered what**:

| Concern | Route | Effect on `commodities` (remaining need) | Effect on commander history |
|---|---|---|---|
| Journal depot truth | **`PATCH /api/project/{buildId}`** with **`colonisationConstructionDepot`** | Sets/syncs remaining need from `ResourcesRequired` (Required − Provided) | None |
| Scratch create / link | **`PUT /api/project`** with depot snapshot + commodity totals | Initial project need map | None |
| Attributed delivery | **`POST /api/project/{buildId}/contribute/{cmdr}`** | **None** — history/ledger only | Adds commander contribution rows |
| Manual / web deliver | **`POST /api/project/{buildId}/supply/{cmdr}`** | **Subtracts** body amounts from stored need, then contributes | Adds contribution (same delivery) |

**Journal-aware client pattern (RavenColonial EDMC plugin, v1.6.7+):**

1. **`ColonisationConstructionDepot`** → **`PATCH`** with full depot snapshot (skip if create **`PUT`** already sent the same snapshot on a fresh dock).
2. **`ColonisationContribution`** → **`POST …/contribute/{cmdr}`** only (never **`POST …/supply/{cmdr}`**).
3. Do **not** use legacy **`POST /api/project/{buildId}`** for depot sync — prefer **`PATCH`** with **`colonisationConstructionDepot`**.

**Why `/contribute` and `/supply` both exist:** `/contribute` lets clients grow the historical record without mutating remaining need (the depot journal is the source of truth for need). `/supply` is for clients **without** journal depot events: it applies the delivery to need and history in one step.

See also [ACTION_MAP_API_FLOWS.md](ACTION_MAP_API_FLOWS.md) for journal event ↔ route mapping in this plugin.

### Fleet Carrier methods

| Method | Path | Notes / applicability |
|---|---|---|
| `PATCH` | `/api/fc/{marketId}/cargo` | Delta update to FC cargo (add/subtract amounts). Does not modify unmentioned commodities. Use for event-driven cargo moves. |
| `POST` | `/api/fc/{marketId}/cargo` | Replace/update mentioned FC commodity amounts with explicit values. Use for snapshot/reconciliation style writes. |
| `PATCH` | `/api/fc/{marketId}` | Update FC metadata fields (for example display name). |
| `POST` | `/api/fc/{marketId}/spansh` | Create FC record from Spansh seed data. |

### Commander and linkage methods

| Method | Path | Notes / applicability |
|---|---|---|
| `GET` / `PATCH` | `/api/cmdr/{cmdr}` | Read or update basic commander profile data. |
| `PUT` / `DELETE` | `/api/cmdr/{cmdr}/fc/{marketId}` | Explicitly link/unlink FC ownership/association to commander. |
| `PUT` / `DELETE` | `/api/project/{buildId}/fc/{marketId}` | Explicitly link/unlink FC to a specific project (project-scoped FC association). |

### System lookup methods

| Method | Path | Notes / applicability |
|---|---|---|
| `GET` | `/api/system/{systemAddress}/{marketId}` | Resolve active project by location context when `buildId` is unknown. Typical first step before writing project updates. |
| `GET` | `/api/project/{buildId}/last` | Lightweight change check; use to detect freshness before heavier reads. |

## Request Body Confidence Labels

This edition keeps the OpenAPI declaration separate from client-code evidence. The labels mean:

- **OpenAPI-declared**: the OpenAPI document explicitly declares the body schema.
- **Client-confirmed**: the request body is visible in `RavenColonialWeb` or `SrvSurvey` source code.
- **Client-confirmed bodyless**: the client source calls the endpoint with no request body.
- **Inferred from client model**: the client sends a serialized class/interface that is not fully declared by OpenAPI, but its fields are visible in source.
- **Unknown / not confirmed**: neither the OpenAPI spec nor the inspected clients clearly declare the body shape.

## Client-Confirmed Request Body Index

These are the endpoints where the inspected clients provide useful body evidence beyond, or in addition to, the OpenAPI file. Endpoints remain grouped categorically.

### Chain

| Endpoint | Body format | Evidence | Example |
|---|---|---|---|
| [`PUT /api/Chain/create`](#put-apichaincreate) | `ChainCreate` / `{ name: string }` | Client-confirmed + OpenAPI-declared | `{ "name": "My chain" }` |
| [`POST /api/Chain/{id}/setName`](#post-apichainidsetname) | JSON string | Client-confirmed + OpenAPI-declared | `"New name"` |
| [`POST /api/Chain/{id}/setNotes`](#post-apichainidsetnotes) | JSON string | Client-confirmed + OpenAPI-declared | `"Notes here"` |
| [`POST /api/Chain/{id}/setPrivate`](#post-apichainidsetprivate) | JSON boolean | Client-confirmed + OpenAPI-declared | `true` |
| [`POST /api/Chain/{id}/setCmdrs`](#post-apichainidsetcmdrs) | `string[]` commander names | Client-confirmed + OpenAPI-declared | `["cmdr one", "cmdr two"]` |
| [`POST /api/Chain/{id}/setFCs`](#post-apichainidsetfcs) | `number[]` market IDs | Client-confirmed + OpenAPI-declared | `[3700000000]` |
| [`POST /api/Chain/{id}/{id64}/setFCs`](#post-apichainidid64setfcs) | `number[]` market IDs | Client-confirmed + OpenAPI-declared | `[3700000000]` |
| [`POST /api/Chain/{id}/setSystems`](#post-apichainidsetsystems) | `string[]` system names | Client-confirmed + OpenAPI-declared | `["Sol", "Achenar"]` |

### Commander

| Endpoint | Body format | Evidence | Example |
|---|---|---|---|
| [`PATCH /api/Cmdr/{cmdr}`](#patch-apicmdrcmdr) | `CommanderPatch` / `{ displayName: string }` | Client-confirmed + OpenAPI-declared | `{ "displayName": "CMDR Name" }` |
| [`POST /api/Cmdr/{cmdr}/hiddenIDs`](#post-apicmdrcmdrhiddenids) | `string[]` build IDs | Client-confirmed | `["build-id-1", "build-id-2"]` |
| [`POST /api/Cmdr/currentShip`](#post-apicmdrcurrentship) | `CmdrShip` | Client-confirmed + OpenAPI-declared | See endpoint section. |
| [`POST /api/Cmdr/fleetCarriers`](#post-apicmdrfleetcarriers) | No body | Client-confirmed bodyless | — |
| [`PUT /api/Cmdr/{cmdr}/primary/{buildId}`](#put-apicmdrcmdrprimarybuildid) | No body | Client-confirmed bodyless | — |
| [`DELETE /api/Cmdr/{cmdr}/primary`](#delete-apicmdrcmdrprimary) | No body | Client-confirmed bodyless | — |
| [`PUT /api/Cmdr/{cmdr}/fc/{marketId}`](#put-apicmdrcmdrfcmarketid) | No body | Client-confirmed bodyless | — |
| [`DELETE /api/Cmdr/{cmdr}/fc/{marketId}`](#delete-apicmdrcmdrfcmarketid) | No body | Client-confirmed bodyless | — |

### Fleet Carrier

| Endpoint | Body format | Evidence | Example |
|---|---|---|---|
| [`PUT /api/FC/{marketId}`](#put-apifcmarketid) | `FleetCarrierView` / SrvSurvey `FleetCarrier` | Client-confirmed + OpenAPI-declared | See endpoint section. |
| [`PATCH /api/FC/{marketId}`](#patch-apifcmarketid) | `{ displayName: string }` | Client-confirmed + OpenAPI-declared | `{ "displayName": "Carrier Display Name" }` |
| [`POST /api/FC/{marketId}/cargo`](#post-apifcmarketidcargo) | `Cargo` = object map of commodity name to number. Replaces mentioned amounts. | Client-confirmed | `{ "tritium": 500, "steel": 120 }` |
| [`PATCH /api/FC/{marketId}/cargo`](#patch-apifcmarketidcargo) | `Cargo` = object map of commodity name to signed delta. | Client-confirmed | `{ "tritium": -20, "steel": 120 }` |
| [`POST /api/FC/{marketId}/spansh`](#post-apifcmarketidspansh) | No body | Client-confirmed bodyless | — |
| [`POST /api/FC/{nameOrNum}/location/{systemName}`](#post-apifcnameornumlocationsystemname) | No body | Client-confirmed bodyless | — |

### Project

| Endpoint | Body format | Evidence | Example |
|---|---|---|---|
| [`PUT /api/project`](#put-apiproject) | `ProjectCreate` / `CreateProject` | Client-confirmed + OpenAPI-declared | See endpoint section. |
| [`PATCH /api/project/{buildId}`](#patch-apiprojectbuildid) | `ProjectUpdate` — depot sync: **`colonisationConstructionDepot`** + `commodities` / `maxNeed`; other fields merge-style | RavenColonial EDMC + OpenAPI-declared | `{ "buildId": "…", "colonisationConstructionDepot": {…}, "commodities": {…}, "maxNeed": 0 }` |
| [`POST /api/project/{buildId}`](#post-apiprojectbuildid) | `ProjectUpdate` object | SrvSurvey legacy (`updateProject`); **prefer PATCH for depot need** | `{ "buildId": "...", "notes": "Updated notes" }` |
| [`POST /api/project/stats`](#post-apiprojectstats) | `string[]` build IDs | Client-confirmed + OpenAPI-declared | `["build-id-1", "build-id-2"]` |
| [`POST /api/project/poll`](#post-apiprojectpoll) | `string[]` build IDs | Client-confirmed | `["build-id-1", "build-id-2"]` |
| [`POST /api/project/ships`](#post-apiprojectships) | `string[]` build IDs | Client-confirmed + OpenAPI-declared | `["build-id-1"]` |
| [`POST /api/project/markets`](#post-apiprojectmarkets) | `FindMarketsOptions` | Client-confirmed + OpenAPI-declared | See endpoint section. |
| [`POST /api/project/{buildId}/markets`](#post-apiprojectbuildidmarkets) | `FindMarketsOptions` | OpenAPI-declared; web uses global variant | See endpoint section. |
| [`POST /api/project/{buildId}/supply/{cmdr}`](#post-apiprojectbuildidsupplycmdr) | `Cargo` map — **subtracts** from remaining need, then contributes | Client-confirmed (web `deliverToSite`) | `{ "steel": 64, "titanium": 32 }` |
| [`PUT /api/project/{buildId}/supply/{cmdr}`](#put-apiprojectbuildidsupplycmdr) | `Cargo`; likely replacement/set semantics | OpenAPI-declared shape; not observed in inspected clients | `{ "steel": 64 }` |
| [`POST /api/project/{buildId}/contribute/{cmdr}`](#post-apiprojectbuildidcontributecmdr) | `Cargo` delta map — **history only**; does not change remaining need | SrvSurvey + RavenColonial EDMC | `{ "steel": 64 }` |
| [`POST /api/system/{id64}/{marketId}/contribute/{cmdr}`](#post-apisystemid64marketidcontributecmdr) | `Cargo` delta map | OpenAPI-declared shape; route-adjacent to SrvSurvey contribute flow | `{ "steel": 64 }` |
| [`POST /api/project/{buildId}/ready`](#post-apiprojectbuildidready) | `string[]` commodity names | Client-confirmed | `["steel", "titanium"]` |
| [`DELETE /api/project/{buildId}/ready`](#delete-apiprojectbuildidready) | `string[]` commodity names | Client-confirmed | `["steel", "titanium"]` |
| [`PUT /api/project/{buildId}/ready`](#put-apiprojectbuildidready) | `string[]` commodity names | OpenAPI-declared shape; not observed in inspected clients | `["steel"]` |
| [`POST /api/project/from/{id64}/{systemSiteId}/{buildType}`](#post-apiprojectfromid64systemsiteidbuildtype) | No body | Client-confirmed bodyless | — |
| [`POST /api/project/{buildId}/complete`](#post-apiprojectbuildidcomplete) | No body | Client-confirmed bodyless | — |
| [`PUT /api/project/{buildId}/link/{cmdr}`](#put-apiprojectbuildidlinkcmdr) | No body | Client-confirmed bodyless | — |
| [`DELETE /api/project/{buildId}/link/{cmdr}`](#delete-apiprojectbuildidlinkcmdr) | No body | Client-confirmed bodyless | — |
| [`PUT /api/project/{buildId}/assign/{cmdr}/{commodity}`](#put-apiprojectbuildidassigncmdrcommodity) | No body | Client-confirmed bodyless | — |
| [`DELETE /api/project/{buildId}/assign/{cmdr}/{commodity}`](#delete-apiprojectbuildidassigncmdrcommodity) | No body | Client-confirmed bodyless | — |
| [`PUT /api/project/{buildId}/fc/{marketId}`](#put-apiprojectbuildidfcmarketid) | No body | Client-confirmed bodyless | — |
| [`DELETE /api/project/{buildId}/fc/{marketId}`](#delete-apiprojectbuildidfcmarketid) | No body | Client-confirmed bodyless | — |

### Quest

| Endpoint | Body format | Evidence | Example |
|---|---|---|---|
| [`POST /api/Quest/publish`](#post-apiquestpublish) | `QuestDef` / SrvSurvey `DefQuest` | SrvSurvey-confirmed + OpenAPI-declared | See endpoint section. |
| [`POST /api/Quest/save`](#post-apiquestsave) | object map from quest ref string to player quest state | SrvSurvey-confirmed; OpenAPI only says `object` | `{ "publisher/id/version": { } }` |
| [`POST /api/Quest/load`](#post-apiquestload) | No body, uses auth header | SrvSurvey-confirmed bodyless | — |

### System / System v2

| Endpoint | Body format | Evidence | Example |
|---|---|---|---|
| [`POST /api/System/{systemName}/mocks/{name}`](#post-apisystemsystemnamemocksname) | `MockMinPayload` | Client-confirmed + OpenAPI-declared | See endpoint section. |
| [`PUT /api/v2/system/{nameOrNum}/sites`](#put-apiv2systemnameornumsites) | `SitesPut` | SrvSurvey-confirmed + OpenAPI-declared | See endpoint section. |
| [`PATCH /api/v2/system/{nameOrNum}/sites/{siteId}`](#patch-apiv2systemnameornumsitessiteid) | partial `Site` repair fields (`marketId`, `name`) | RavenColonial EDMC client-confirmed | `{ "marketId": 4310555555 }` |
| [`PUT /api/v2/system/{nameOrNum}/bodies`](#put-apiv2systemnameornumbodies) | `Bod[]` | SrvSurvey-confirmed + OpenAPI-declared | See endpoint section. |
| [`POST /api/v2/system/{nameOrNum}/import/{type}`](#post-apiv2systemnameornumimporttype) | No body in SrvSurvey for `type = bodies` | SrvSurvey-confirmed bodyless for bodies import | — |

### GGG / Misc / Login

| Endpoint | Body format | Evidence | Example |
|---|---|---|---|
| [`PUT /api/GGG/create`](#put-apigggcreate) | `CreateGGG` object: `cmdr`, `tag`, `starPos`, `json` | SrvSurvey-confirmed + OpenAPI-declared | See endpoint section. |
| [`POST /api/login`](#post-apilogin) | `LoginBody` | OpenAPI-declared | See endpoint section. |
| [`POST /api/misc/feedback`](#post-apimiscfeedback) | `FeedbackBody` | OpenAPI-declared | See endpoint section. |

## Common Payload Shapes Confirmed by Client Code

### Cargo map

`Cargo` is a JSON object where each property name is a lowercase/language-agnostic commodity key and each value is a numeric quantity. For PATCH/delta endpoints, values may be positive or negative.

```json
{
  "tritium": 500,
  "steel": 120,
  "liquidoxygen": 64
}
```

### Current ship cargo

```json
{
  "cmdr": "CommanderName",
  "name": "Ship Name",
  "type": "type9",
  "time": "2026-05-02T00:00:00Z",
  "maxCargo": 784,
  "cargo": {
    "tritium": 500,
    "steel": 120
  }
}
```

### String array payload

Used for build IDs, commodity names, commander names, and system names depending on endpoint.

```json
["item-one", "item-two"]
```


<a id="schema-backed-endpoint-summary"></a>

## Schema-Backed Endpoint Summary

These are the endpoints that reference named OpenAPI component schemas in either the request body or main response. Tap an endpoint to jump to its detailed section.

### Chain

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`PUT /api/Chain/create`](#put-apichaincreate) | [`ChainCreate`](#schema-chaincreate) | [`Chain`](#schema-chain) |
| [`DELETE /api/Chain/delete/{id}`](#delete-apichaindeleteid) | — | [`Chain`](#schema-chain) |
| [`GET /api/Chain/{id}`](#get-apichainid) | — | [`Chain`](#schema-chain) |
| [`POST /api/Chain/{id}/setName`](#post-apichainidsetname) | `string` | [`Chain`](#schema-chain) |
| [`POST /api/Chain/{id}/setNotes`](#post-apichainidsetnotes) | `string` | [`Chain`](#schema-chain) |
| [`POST /api/Chain/{id}/setPrivate`](#post-apichainidsetprivate) | `boolean` | [`Chain`](#schema-chain) |
| [`POST /api/Chain/{id}/setCmdrs`](#post-apichainidsetcmdrs) | array of `string` | [`Chain`](#schema-chain) |
| [`POST /api/Chain/{id}/setFCs`](#post-apichainidsetfcs) | array of `integer` \| `string` | [`Chain`](#schema-chain) |
| [`POST /api/Chain/{id}/{id64}/setFCs`](#post-apichainidid64setfcs) | array of `integer` \| `string` | [`Chain`](#schema-chain) |
| [`POST /api/Chain/{id}/setSystems`](#post-apichainidsetsystems) | array of `string` | [`Chain`](#schema-chain) |

### Cmdr

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`GET /api/Cmdr`](#get-apicmdr) | — | [`CommanderView`](#schema-commanderview) |
| [`GET /api/Cmdr/{cmdr}`](#get-apicmdrcmdr) | — | [`CommanderView`](#schema-commanderview) |
| [`PATCH /api/Cmdr/{cmdr}`](#patch-apicmdrcmdr) | [`CommanderPatch`](#schema-commanderpatch) | [`CommanderView`](#schema-commanderview) |
| [`GET /api/Cmdr/{cmdr}/active`](#get-apicmdrcmdractive) | — | array of [`ProjectView`](#schema-projectview) |
| [`GET /api/Cmdr/{cmdr}/refs`](#get-apicmdrcmdrrefs) | — | array of [`ProjectRef`](#schema-projectref) |
| [`GET /api/Cmdr/viewAll`](#get-apicmdrviewall) | — | array of [`FleetCarrierView`](#schema-fleetcarrierview) |
| [`GET /api/Cmdr/{cmdr}/fc`](#get-apicmdrcmdrfc) | — | array of [`FleetCarrierView`](#schema-fleetcarrierview) |
| [`GET /api/Cmdr/{cmdr}/fc/all`](#get-apicmdrcmdrfcall) | — | array of [`FleetCarrierView`](#schema-fleetcarrierview) |
| [`PUT /api/Cmdr/{cmdr}/fc/{marketId}`](#put-apicmdrcmdrfcmarketid) | — | array of [`ProjectFC`](#schema-projectfc) |
| [`POST /api/Cmdr/fleetCarriers`](#post-apicmdrfleetcarriers) | — | array of [`FleetCarrierView`](#schema-fleetcarrierview) |
| [`POST /api/Cmdr/currentShip`](#post-apicmdrcurrentship) | [`CmdrShip`](#schema-cmdrship) | array of `string` |
| [`GET /api/Cmdr/{cmdr}/map/architect`](#get-apicmdrcmdrmaparchitect) | — | [`MapData`](#schema-mapdata) |
| [`GET /api/Cmdr/nexus`](#get-apicmdrnexus) | — | array of [`Summary`](#schema-summary) |

### FC

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`GET /api/FC/query/{name}`](#get-apifcqueryname) | — | array of [`QuickSearchStation`](#schema-quicksearchstation) |
| [`GET /api/FC/find/{name}`](#get-apifcfindname) | — | array of [`QuickSearchStation`](#schema-quicksearchstation) |
| [`POST /api/FC/{marketId}/spansh`](#post-apifcmarketidspansh) | — | [`FleetCarrierView`](#schema-fleetcarrierview) |
| [`GET /api/FC/{marketId}`](#get-apifcmarketid) | — | [`FleetCarrierView`](#schema-fleetcarrierview) |
| [`PUT /api/FC/{marketId}`](#put-apifcmarketid) | [`FleetCarrierView`](#schema-fleetcarrierview) | [`FleetCarrierView`](#schema-fleetcarrierview) |
| [`PATCH /api/FC/{marketId}`](#patch-apifcmarketid) | [`FleetCarrierPatch`](#schema-fleetcarrierpatch) | [`FleetCarrierView`](#schema-fleetcarrierview) |

### GGG

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`PUT /api/GGG/create`](#put-apigggcreate) | [`CreateGGG`](#schema-createggg) | — |
| [`GET /api/GGG/json`](#get-apigggjson) | — | array of [`GGG`](#schema-ggg) |

### Misc

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`POST /api/login`](#post-apilogin) | [`LoginBody`](#schema-loginbody) | — |
| [`POST /api/misc/feedback`](#post-apimiscfeedback) | [`FeedbackBody`](#schema-feedbackbody) | — |
| [`GET /api/misc/nicknames`](#get-apimiscnicknames) | — | array of [`SysID64`](#schema-sysid64) |

### Project

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`PUT /api/project`](#put-apiproject) | [`ProjectCreate`](#schema-projectcreate) | [`ProjectView`](#schema-projectview) |
| [`GET /api/project/{buildId}`](#get-apiprojectbuildid) | — | [`ProjectView`](#schema-projectview) |
| [`POST /api/project/{buildId}`](#post-apiprojectbuildid) | [`ProjectUpdate`](#schema-projectupdate) | [`ProjectView`](#schema-projectview) |
| [`PATCH /api/project/{buildId}`](#patch-apiprojectbuildid) | [`ProjectUpdate`](#schema-projectupdate) | [`ProjectView`](#schema-projectview) |
| [`POST /api/project/{buildId}/cargo/default`](#post-apiprojectbuildidcargodefault) | — | [`ProjectView`](#schema-projectview) |
| [`PUT /api/project/{buildId}/fc/name/{name}`](#put-apiprojectbuildidfcnamename) | — | array of [`ProjectFC`](#schema-projectfc) |
| [`PUT /api/project/{buildId}/fc/{marketId}`](#put-apiprojectbuildidfcmarketid) | — | array of [`ProjectFC`](#schema-projectfc) |
| [`GET /api/project/{buildId}/ships`](#get-apiprojectbuildidships) | — | array of [`CmdrShip`](#schema-cmdrship) |
| [`POST /api/project/ships`](#post-apiprojectships) | array of `string` | array of [`CmdrShip`](#schema-cmdrship) |
| [`GET /api/project/{buildId}/stats`](#get-apiprojectbuildidstats) | — | [`SupplyStatsSummary`](#schema-supplystatssummary) |
| [`POST /api/project/stats`](#post-apiprojectstats) | array of `string` | array of [`SupplyStatsSummary`](#schema-supplystatssummary) |
| [`POST /api/project/{buildId}/markets`](#post-apiprojectbuildidmarkets) | [`FindMarketsOptions`](#schema-findmarketsoptions) | [`FoundMarkets`](#schema-foundmarkets) |
| [`POST /api/project/markets`](#post-apiprojectmarkets) | [`FindMarketsOptions`](#schema-findmarketsoptions) | [`FoundMarkets`](#schema-foundmarkets) |
| [`POST /api/project/createFrom/{systemSiteId}/{buildType}`](#post-apiprojectcreatefromsystemsiteidbuildtype) | — | [`ProjectView`](#schema-projectview) |
| [`POST /api/project/from/{id64}/{systemSiteId}/{buildType}`](#post-apiprojectfromid64systemsiteidbuildtype) | — | [`ProjectView`](#schema-projectview) |

### Quest

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`POST /api/Quest/publish`](#post-apiquestpublish) | [`QuestDef`](#schema-questdef) | — |
| [`GET /api/Quest/published`](#get-apiquestpublished) | — | array of [`QuestSummary`](#schema-questsummary) |
| [`GET /api/Quest/{publisher}/{id}/{version}`](#get-apiquestpublisheridversion) | — | [`QuestDef`](#schema-questdef) |
| [`POST /api/Quest/save`](#post-apiquestsave) | [`JsonElement`](#schema-jsonelement) | — |

### System

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`GET /api/System/{id64OrSystemName}`](#get-apisystemid64orsystemname) | — | array of [`ProjectRef`](#schema-projectref) |
| [`GET /api/System/{systemName}/complete`](#get-apisystemsystemnamecomplete) | — | array of [`ProjectRefComplete`](#schema-projectrefcomplete) |
| [`GET /api/System/{systemName}/all`](#get-apisystemsystemnameall) | — | array of [`ProjectRef`](#schema-projectref) |
| [`GET /api/System/{id64}/{marketId}`](#get-apisystemid64marketid) | — | [`ProjectView`](#schema-projectview) |
| [`GET /api/System/{systemName}/mocks/{name}`](#get-apisystemsystemnamemocksname) | — | [`MockMinPayload`](#schema-mockminpayload) |
| [`POST /api/System/{systemName}/mocks/{name}`](#post-apisystemsystemnamemocksname) | [`MockMinPayload`](#schema-mockminpayload) | `string` |

### System2

| Endpoint | Request Body | Main Response |
|---|---|---|
| [`POST /api/v2/system/{nameOrNum}/import/{type}`](#post-apiv2systemnameornumimporttype) | — | [`Sys`](#schema-sys) |
| [`GET /api/v2/system/{nameOrNum}/.{rev}`](#get-apiv2systemnameornumrev) | — | [`Sys`](#schema-sys) |
| [`GET /api/v2/system/{nameOrNum}`](#get-apiv2systemnameornum) | — | [`Sys`](#schema-sys) |
| [`GET /api/v2/system/{nameOrNum}/!{saveName}`](#get-apiv2systemnameornumsavename) | — | [`Sys`](#schema-sys) |
| [`GET /api/v2/system/{nameOrNum}/sites`](#get-apiv2systemnameornumsites) | — | array of [`Site`](#schema-site) |
| [`PUT /api/v2/system/{nameOrNum}/sites`](#put-apiv2systemnameornumsites) | [`SitesPut`](#schema-sitesput) | [`Sys`](#schema-sys) |
| [`GET /api/v2/system/{nameOrNum}/bodies`](#get-apiv2systemnameornumbodies) | — | array of [`Bod`](#schema-bod) |
| [`PUT /api/v2/system/{nameOrNum}/bodies`](#put-apiv2systemnameornumbodies) | array of [`Bod`](#schema-bod) | array of [`Bod`](#schema-bod) |
| [`PUT /api/v2/system/{nameOrNum}/{bodyNum}/features`](#put-apiv2systemnameornumbodynumfeatures) | array of [`BodyFeature`](#schema-bodyfeature) | array of [`Bod`](#schema-bod) |
| [`GET /api/v2/system/{nameOrNum}/spanshEconomies`](#get-apiv2systemnameornumspansheconomies) | — | array of [`GetRealEconomies`](#schema-getrealeconomies) |
| [`GET /api/v2/system/{id64}/snapshot/{architect}`](#get-apiv2systemid64snapshotarchitect) | — | array of [`Bod`](#schema-bod) |
| [`PUT /api/v2/system/{id64}/snapshot`](#put-apiv2systemid64snapshot) | [`SysSnapshot`](#schema-syssnapshot) | array of [`Bod`](#schema-bod) |
| [`GET /api/v2/system/snapshots`](#get-apiv2systemsnapshots) | — | array of [`SysSnapshot`](#schema-syssnapshot) |
| [`GET /api/v2/system/{nameOrNum}/popHistory`](#get-apiv2systemnameornumpophistory) | — | array of [`History`](#schema-history) |

<a id="schema-backed-endpoints"></a>

## Schema-Backed Endpoints

This section contains the detailed endpoint documentation for API calls that have declared component schemas.

## Chain

### `PUT /api/Chain/create`

**Purpose:** Create or replace create data for `/api/Chain/create`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`ChainCreate`](#schema-chaincreate)

Example shape:

```json
{
  "name": "string"
}
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `nexus.create`. Body is `{ name: string }`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `DELETE /api/Chain/delete/{id}`

**Purpose:** Delete/remove delete data for `/api/Chain/delete/{id}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `GET /api/Chain/{id}`

**Purpose:** Retrieve Chain data for `/api/Chain/{id}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `POST /api/Chain/{id}/setName`

**Purpose:** Submit/update setName data for `/api/Chain/{id}/setName`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: `string`

Example shape:

```json
"string"
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `nexus.setName`. Body is a JSON string.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `POST /api/Chain/{id}/setNotes`

**Purpose:** Submit/update setNotes data for `/api/Chain/{id}/setNotes`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: `string`

Example shape:

```json
"string"
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `nexus.setNotes`. Body is a JSON string.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `POST /api/Chain/{id}/setPrivate`

**Purpose:** Submit/update setPrivate data for `/api/Chain/{id}/setPrivate`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: `boolean`

Example shape:

```json
true
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `nexus.setPrivate`. Body is a JSON boolean.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `POST /api/Chain/{id}/setCmdrs`

**Purpose:** Submit/update setCmdrs data for `/api/Chain/{id}/setCmdrs`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `nexus.setCmdrs`. Body is a string array.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `POST /api/Chain/{id}/setFCs`

**Purpose:** Submit/update setFCs data for `/api/Chain/{id}/setFCs`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `integer` | `string`

Example shape:

```json
[
  0
]
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `nexus.setFCs`. Body is an array of fleet-carrier market IDs.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `POST /api/Chain/{id}/{id64}/setFCs`

**Purpose:** Submit/update setFCs data for `/api/Chain/{id}/{id64}/setFCs`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |
| `id64` | `path` | `true` | `integer` \| `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `integer` | `string`

Example shape:

```json
[
  0
]
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `nexus.setSysFCs`. Body is an array of fleet-carrier market IDs.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

### `POST /api/Chain/{id}/setSystems`

**Purpose:** Submit/update setSystems data for `/api/Chain/{id}/setSystems`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `nexus.setSystems`. Body is a string array of system names.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Chain`](#schema-chain) |

## Cmdr

### `GET /api/Cmdr`

**Purpose:** Retrieve Cmdr data for `/api/Cmdr`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`CommanderView`](#schema-commanderview) |

### `GET /api/Cmdr/{cmdr}`

**Purpose:** Retrieve Cmdr data for `/api/Cmdr/{cmdr}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`CommanderView`](#schema-commanderview) |

### `PATCH /api/Cmdr/{cmdr}`

**Purpose:** Partially update Cmdr data for `/api/Cmdr/{cmdr}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`CommanderPatch`](#schema-commanderpatch)

Example shape:

```json
{
  "displayName": "string"
}
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `cmdr.updateCmdr`. Body is `{ displayName: string }`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`CommanderView`](#schema-commanderview) |

### `GET /api/Cmdr/{cmdr}/active`

**Purpose:** Retrieve active data for `/api/Cmdr/{cmdr}/active`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`ProjectView`](#schema-projectview) |

### `GET /api/Cmdr/{cmdr}/refs`

**Purpose:** Retrieve refs data for `/api/Cmdr/{cmdr}/refs`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`ProjectRef`](#schema-projectref) |

### `GET /api/Cmdr/viewAll`

**Purpose:** Retrieve viewAll data for `/api/Cmdr/viewAll`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`FleetCarrierView`](#schema-fleetcarrierview) |

### `GET /api/Cmdr/{cmdr}/fc`

**Purpose:** Retrieve fc data for `/api/Cmdr/{cmdr}/fc`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`FleetCarrierView`](#schema-fleetcarrierview) |

### `GET /api/Cmdr/{cmdr}/fc/all`

**Purpose:** Retrieve all data for `/api/Cmdr/{cmdr}/fc/all`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`FleetCarrierView`](#schema-fleetcarrierview) |

### `PUT /api/Cmdr/{cmdr}/fc/{marketId}`

**Purpose:** Create or replace fc data for `/api/Cmdr/{cmdr}/fc/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`ProjectFC`](#schema-projectfc) |

### `POST /api/Cmdr/fleetCarriers`

**Purpose:** Submit/update fleetCarriers data for `/api/Cmdr/fleetCarriers`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb `cmdr.fetchMyFCs`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`FleetCarrierView`](#schema-fleetcarrierview) |

### `POST /api/Cmdr/currentShip`

**Purpose:** Submit/update currentShip data for `/api/Cmdr/currentShip`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`CmdrShip`](#schema-cmdrship)

Example shape:

```json
{
  "cmdr": "string",
  "name": "string",
  "type": "string",
  "time": "2026-05-01T00:00:00Z",
  "maxCargo": 0,
  "cargo": {}
}
```

**Body confidence:** OpenAPI-declared and SrvSurvey-confirmed by `publishCurrentShip`. Body is `CmdrShip`; `cargo` is a commodity-to-number map.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of `string` |

### `GET /api/Cmdr/{cmdr}/map/architect`

**Purpose:** Retrieve architect data for `/api/Cmdr/{cmdr}/map/architect`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`MapData`](#schema-mapdata) |

### `GET /api/Cmdr/nexus`

**Purpose:** Retrieve nexus data for `/api/Cmdr/nexus`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`Summary`](#schema-summary) |

## FC

### `GET /api/FC/query/{name}`

**Purpose:** Retrieve query data for `/api/FC/query/{name}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `name` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`QuickSearchStation`](#schema-quicksearchstation) |

### `GET /api/FC/find/{name}`

**Purpose:** Retrieve find data for `/api/FC/find/{name}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `name` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`QuickSearchStation`](#schema-quicksearchstation) |

### `POST /api/FC/{marketId}/spansh`

**Purpose:** Submit/update spansh data for `/api/FC/{marketId}/spansh`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb `fc.check`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`FleetCarrierView`](#schema-fleetcarrierview) |

### `GET /api/FC/{marketId}`

**Purpose:** Retrieve FC data for `/api/FC/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`FleetCarrierView`](#schema-fleetcarrierview) |

### `PUT /api/FC/{marketId}`

**Purpose:** Create or replace FC data for `/api/FC/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`FleetCarrierView`](#schema-fleetcarrierview)

Example shape:

```json
{
  "marketId": 0,
  "name": "string",
  "displayName": "string",
  "owner": "string",
  "cargo": {},
  "systemName": "string",
  "id64": 0,
  "starPos": [
    0
  ]
}
```

**Body confidence:** OpenAPI-declared and SrvSurvey-confirmed by `publishFC`. Body is full fleet-carrier data; cargo is untouched if null in SrvSurvey's comment.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`FleetCarrierView`](#schema-fleetcarrierview) |

### `PATCH /api/FC/{marketId}`

**Purpose:** Partially update FC data for `/api/FC/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`FleetCarrierPatch`](#schema-fleetcarrierpatch)

Example shape:

```json
{
  "displayName": "string"
}
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `fc.updateFields`. Body is `{ displayName: string }`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`FleetCarrierView`](#schema-fleetcarrierview) |

## GGG

### `PUT /api/GGG/create`

**Purpose:** Create or replace create data for `/api/GGG/create`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`CreateGGG`](#schema-createggg)

Example shape:

```json
{
  "cmdr": "string",
  "tag": "string",
  "starPos": [
    0
  ],
  "json": "string"
}
```

**Body confidence:** OpenAPI-declared and SrvSurvey-confirmed by `uploadGGG`. Body contains `cmdr`, `tag`, `starPos`, and `json`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/GGG/json`

**Purpose:** Retrieve json data for `/api/GGG/json`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`GGG`](#schema-ggg) |

## Misc

### `POST /api/login`

**Purpose:** Submit/update login data for `/api/login`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`LoginBody`](#schema-loginbody)

Example shape:

```json
{
  "access_token": "string",
  "expires_in": 0,
  "refresh_token": "string",
  "token_type": "string"
}
```

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `POST /api/misc/feedback`

**Purpose:** Submit/update feedback data for `/api/misc/feedback`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`FeedbackBody`](#schema-feedbackbody)

Example shape:

```json
{
  "subject": "string",
  "contact": "string",
  "message": "string",
  "images": [
    "string"
  ]
}
```

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/misc/nicknames`

**Purpose:** Retrieve nicknames data for `/api/misc/nicknames`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`SysID64`](#schema-sysid64) |

## Project

### `PUT /api/project`

**Purpose:** Create a new build project (`PUT /api/project`). Include **`colonisationConstructionDepot`**, **`commodities`**, and **`maxNeed`** when the client has a docked **`ColonisationConstructionDepot`** journal snapshot (RavenColonial EDMC create and link flows).

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`ProjectCreate`](#schema-projectcreate)

Example shape:

```json
{
  "marketId": 0,
  "systemAddress": 0,
  "buildName": "string",
  "systemSiteId": "string",
  "commodities": {},
  "colonisationConstructionDepot": {
    "timestamp": "...",
    "event": "...",
    "marketID": "...",
    "constructionProgress": "...",
    "constructionComplete": "...",
    "constructionFailed": "...",
    "resourcesRequired": "..."
  },
  "buildType": "string",
  "systemName": "string",
  "starPos": [
    0
  ],
  "bodyNum": 0,
  "bodyName": "string",
  "architectName": "string",
  "discordLink": "string",
  "timeDue": "2026-05-01T00:00:00Z",
  "isPrimaryPort": true,
  "commanders": {},
  "notes": "string",
  "maxNeed": 0,
  "bodyType": "string",
  "bodyFeatures": [
    "..."
  ]
}
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `project.create` and SrvSurvey `create`. Body is a project creation object.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`ProjectView`](#schema-projectview) |

### `GET /api/project/{buildId}`

**Purpose:** Retrieve project data for `/api/project/{buildId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`ProjectView`](#schema-projectview) |

### `POST /api/project/{buildId}`

**Purpose:** Full or partial project update (SrvSurvey `updateProject` legacy path). For **remaining need** driven by **`ColonisationConstructionDepot`**, prefer **`PATCH /api/project/{buildId}`** with the full depot snapshot — the RavenColonial EDMC plugin does not call this route for depot sync (v1.6.7+).

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`ProjectUpdate`](#schema-projectupdate)

Example shape:

```json
{
  "timestamp": "2026-05-01T00:00:00Z",
  "eTag": null,
  "buildId": "string",
  "marketId": 0,
  "buildType": "string",
  "buildName": "string",
  "bodyNum": 0,
  "bodyName": "string",
  "factionName": "string",
  "architectName": "string",
  "discordLink": "string",
  "timeDue": "string",
  "timeCompleted": "string",
  "timeStarted": "string",
  "isPrimaryPort": true,
  "notes": "string",
  "maxNeed": 0,
  "commodities": {},
  "colonisationConstructionDepot": {
    "timestamp": "...",
    "event": "...",
    "marketID": "...",
    "constructionProgress": "...",
    "constructionComplete": "...",
    "constructionFailed": "...",
    "resourcesRequired": "..."
  },
  "bodyType": "string"
}
```

**Body confidence:** OpenAPI-declared and SrvSurvey-confirmed by `updateProject`. Body is a `ProjectUpdate` object that includes `buildId` plus changed fields. **Depot-driven need:** use **`PATCH`** with **`colonisationConstructionDepot`** instead (see [Method Applicability Guide — Construction](#construction-remaining-need-vs-delivery-history)).

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`ProjectView`](#schema-projectview) |

### `PATCH /api/project/{buildId}`

**Purpose:** Merge-style partial update. For journal-aware clients, this is the **authoritative route for remaining need**: send the full **`ColonisationConstructionDepot`** journal line plus derived **`commodities`** (per-commodity `RequiredAmount − ProvidedAmount`, clamped ≥ 0) and **`maxNeed`** (sum of required amounts). Also used for metadata (`notes`, `buildName`, …) without depot changes.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`ProjectUpdate`](#schema-projectupdate)

Example shape:

```json
{
  "timestamp": "2026-05-01T00:00:00Z",
  "eTag": null,
  "buildId": "string",
  "marketId": 0,
  "buildType": "string",
  "buildName": "string",
  "bodyNum": 0,
  "bodyName": "string",
  "factionName": "string",
  "architectName": "string",
  "discordLink": "string",
  "timeDue": "string",
  "timeCompleted": "string",
  "timeStarted": "string",
  "isPrimaryPort": true,
  "notes": "string",
  "maxNeed": 0,
  "commodities": {},
  "colonisationConstructionDepot": {
    "timestamp": "...",
    "event": "...",
    "marketID": "...",
    "constructionProgress": "...",
    "constructionComplete": "...",
    "constructionFailed": "...",
    "resourcesRequired": "..."
  },
  "bodyType": "string"
}
```

**Body confidence:** OpenAPI-declared and RavenColonialWeb-confirmed by `project.update`. Body is a partial `ProjectUpdate` / project object. **RavenColonial EDMC** sends depot snapshots on every **`ColonisationConstructionDepot`** change (and after create/link when PUT did not already reflect live remaining need). Commodity keys in outbound maps are normalized to non-negative integers; server template placeholders at **`-1`** may be cleared to **`0`** via a follow-up PATCH when a project response already in hand includes negative keys.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`ProjectView`](#schema-projectview) |

### `POST /api/project/{buildId}/cargo/default`

**Purpose:** Submit/update default data for `/api/project/{buildId}/cargo/default`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`ProjectView`](#schema-projectview) |

### `PUT /api/project/{buildId}/fc/name/{name}`

**Purpose:** Create or replace name data for `/api/project/{buildId}/fc/name/{name}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `name` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`ProjectFC`](#schema-projectfc) |

### `PUT /api/project/{buildId}/fc/{marketId}`

**Purpose:** Create or replace fc data for `/api/project/{buildId}/fc/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb `project.linkFC`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`ProjectFC`](#schema-projectfc) |

### `GET /api/project/{buildId}/ships`

**Purpose:** Retrieve ships data for `/api/project/{buildId}/ships`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`CmdrShip`](#schema-cmdrship) |

### `POST /api/project/ships`

**Purpose:** Submit/update ships data for `/api/project/ships`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `project.getShips`. Body is a string array of build IDs.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`CmdrShip`](#schema-cmdrship) |

### `GET /api/project/{buildId}/stats`

**Purpose:** Retrieve stats data for `/api/project/{buildId}/stats`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`SupplyStatsSummary`](#schema-supplystatssummary) |

### `POST /api/project/stats`

**Purpose:** Submit/update stats data for `/api/project/stats`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `project.getManyStats`. Body is a string array of build IDs.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`SupplyStatsSummary`](#schema-supplystatssummary) |

### `POST /api/project/{buildId}/markets`

**Purpose:** Submit/update markets data for `/api/project/{buildId}/markets`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`FindMarketsOptions`](#schema-findmarketsoptions)

Example shape:

```json
{
  "refSystem": "string",
  "maxDistance": 0,
  "maxArrival": 0,
  "shipSize": "string",
  "noSurface": true,
  "noFC": true,
  "requireNeed": true,
  "hasShipyard": true,
  "commodities": {},
  "buildIds": [
    "string"
  ]
}
```

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`FoundMarkets`](#schema-foundmarkets) |

### `POST /api/project/markets`

**Purpose:** Submit/update markets data for `/api/project/markets`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`FindMarketsOptions`](#schema-findmarketsoptions)

Example shape:

```json
{
  "refSystem": "string",
  "maxDistance": 0,
  "maxArrival": 0,
  "shipSize": "string",
  "noSurface": true,
  "noFC": true,
  "requireNeed": true,
  "hasShipyard": true,
  "commodities": {},
  "buildIds": [
    "string"
  ]
}
```

**Body confidence:** OpenAPI-declared and client-confirmed by RavenColonialWeb `project.findMarkets`. Body is `FindMarketsOptions`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`FoundMarkets`](#schema-foundmarkets) |

### `POST /api/project/createFrom/{systemSiteId}/{buildType}`

**Purpose:** Submit/update {systemSiteId} data for `/api/project/createFrom/{systemSiteId}/{buildType}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `systemSiteId` | `path` | `true` | `string` | — |
| `buildType` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`ProjectView`](#schema-projectview) |

### `POST /api/project/from/{id64}/{systemSiteId}/{buildType}`

**Purpose:** Submit/update {systemSiteId} data for `/api/project/from/{id64}/{systemSiteId}/{buildType}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id64` | `path` | `true` | `integer` \| `string` | — |
| `systemSiteId` | `path` | `true` | `string` | — |
| `buildType` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb `project.createFrom`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`ProjectView`](#schema-projectview) |

## Quest

### `POST /api/Quest/publish`

**Purpose:** Submit/update publish data for `/api/Quest/publish`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`QuestDef`](#schema-questdef)

Example shape:

```json
{
  "firstChapter": "string",
  "objectives": {},
  "msgs": [
    "..."
  ],
  "chapters": {},
  "id": "string",
  "ver": 0,
  "publisher": "string",
  "title": "string",
  "desc": "string"
}
```

**Body confidence:** OpenAPI-declared and SrvSurvey-confirmed by `publishQuest`. Body is a quest definition object.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/Quest/published`

**Purpose:** Retrieve published data for `/api/Quest/published`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`QuestSummary`](#schema-questsummary) |

### `GET /api/Quest/{publisher}/{id}/{version}`

**Purpose:** Retrieve {id} data for `/api/Quest/{publisher}/{id}/{version}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `publisher` | `path` | `true` | `string` | — |
| `id` | `path` | `true` | `string` | — |
| `ver` | `query` | `false` | `number` \| `string` | — |
| `version` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`QuestDef`](#schema-questdef) |

### `POST /api/Quest/save`

**Purpose:** Submit/update save data for `/api/Quest/save`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`JsonElement`](#schema-jsonelement)

**Body confidence:** SrvSurvey-confirmed by `saveCmdrQuests`. Body is an object/dictionary keyed by quest reference string with player-quest values.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

## System

### `GET /api/System/{id64OrSystemName}`

**Purpose:** Retrieve System data for `/api/System/{id64OrSystemName}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id64OrSystemName` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`ProjectRef`](#schema-projectref) |

### `GET /api/System/{systemName}/complete`

**Purpose:** Retrieve complete data for `/api/System/{systemName}/complete`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `systemName` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`ProjectRefComplete`](#schema-projectrefcomplete) |

### `GET /api/System/{systemName}/all`

**Purpose:** Retrieve all data for `/api/System/{systemName}/all`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `systemName` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`ProjectRef`](#schema-projectref) |

### `GET /api/System/{id64}/{marketId}`

**Purpose:** Retrieve {id64} data for `/api/System/{id64}/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id64` | `path` | `true` | `integer` \| `string` | — |
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`ProjectView`](#schema-projectview) |

### `GET /api/System/{systemName}/mocks/{name}`

**Purpose:** Retrieve mocks data for `/api/System/{systemName}/mocks/{name}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `systemName` | `path` | `true` | `string` | — |
| `name` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`MockMinPayload`](#schema-mockminpayload) |

### `POST /api/System/{systemName}/mocks/{name}`

**Purpose:** Submit/update mocks data for `/api/System/{systemName}/mocks/{name}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `systemName` | `path` | `true` | `string` | — |
| `name` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`MockMinPayload`](#schema-mockminpayload)

Example shape:

```json
{
  "etag": null,
  "mocks": [
    "..."
  ]
}
```

**Body confidence:** OpenAPI-declared and RavenColonialWeb-confirmed by `system.saveMocks`. Body is `MockMinPayload`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | `string` |

## System2

### `POST /api/v2/system/{nameOrNum}/import/{type}`

**Purpose:** Submit/update import data for `/api/v2/system/{nameOrNum}/import/{type}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |
| `type` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** SrvSurvey-confirmed bodyless for `type = bodies` via `importSystemBodies`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Sys`](#schema-sys) |

### `GET /api/v2/system/{nameOrNum}/.{rev}`

**Purpose:** Retrieve {nameOrNum} data for `/api/v2/system/{nameOrNum}/.{rev}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |
| `rev` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Sys`](#schema-sys) |

### `GET /api/v2/system/{nameOrNum}`

**Purpose:** Retrieve system data for `/api/v2/system/{nameOrNum}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Sys`](#schema-sys) |

### `GET /api/v2/system/{nameOrNum}/!{saveName}`

**Purpose:** Retrieve {nameOrNum} data for `/api/v2/system/{nameOrNum}/!{saveName}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |
| `saveName` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Sys`](#schema-sys) |

### `GET /api/v2/system/{nameOrNum}/sites`

**Purpose:** Retrieve sites data for `/api/v2/system/{nameOrNum}/sites`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`Site`](#schema-site) |

### `PUT /api/v2/system/{nameOrNum}/sites`

**Purpose:** Create or replace sites data for `/api/v2/system/{nameOrNum}/sites`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`SitesPut`](#schema-sitesput)

Example shape:

```json
{
  "update": [
    "..."
  ],
  "delete": [
    "string"
  ],
  "orderIDs": [
    "string"
  ],
  "architect": "string",
  "nickname": "string",
  "publish": true,
  "notes": "string",
  "saveName": "string",
  "idxCalcLimit": 0,
  "open": true,
  "reserveLevel": "depleted",
  "snapshot": {
    "v": "...",
    "rev": "...",
    "architect": "...",
    "id64": "...",
    "name": "...",
    "nickname": "...",
    "pos": "...",
    "tierPoints": "...",
    "sumEffects": "...",
    "sites": "...",
    "stale": "...",
    "pop": "...",
    "score": "...",
    "fav": "..."
  },
  "slots": {}
}
```

**Body confidence:** OpenAPI-declared and SrvSurvey-confirmed by `updateSystem`. Body is `SitesPut`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | [`Sys`](#schema-sys) |

### `GET /api/v2/system/{nameOrNum}/bodies`

**Purpose:** Retrieve bodies data for `/api/v2/system/{nameOrNum}/bodies`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`Bod`](#schema-bod) |

### `PUT /api/v2/system/{nameOrNum}/bodies`

**Purpose:** Create or replace bodies data for `/api/v2/system/{nameOrNum}/bodies`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of [`Bod`](#schema-bod)

Example shape:

```json
[
  {
    "name": "string",
    "num": 0,
    "distLS": 0,
    "parents": [
      "..."
    ],
    "type": "...",
    "subType": "string",
    "features": [
      "..."
    ],
    "radius": 0,
    "temp": 0,
    "gravity": 0
  }
]
```

**Body confidence:** OpenAPI-declared and SrvSurvey-confirmed by `updateSysBodies`. Body is an array of `Bod` objects.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`Bod`](#schema-bod) |

### `PUT /api/v2/system/{nameOrNum}/{bodyNum}/features`

**Purpose:** Create or replace features data for `/api/v2/system/{nameOrNum}/{bodyNum}/features`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |
| `bodyNum` | `path` | `true` | `integer` \| `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of [`BodyFeature`](#schema-bodyfeature)

Example shape:

```json
[
  "bio"
]
```

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`Bod`](#schema-bod) |

### `GET /api/v2/system/{nameOrNum}/spanshEconomies`

**Purpose:** Retrieve spanshEconomies data for `/api/v2/system/{nameOrNum}/spanshEconomies`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`GetRealEconomies`](#schema-getrealeconomies) |

### `GET /api/v2/system/{id64}/snapshot/{architect}`

**Purpose:** Retrieve snapshot data for `/api/v2/system/{id64}/snapshot/{architect}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id64` | `path` | `true` | `integer` \| `string` | — |
| `architect` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`Bod`](#schema-bod) |

### `PUT /api/v2/system/{id64}/snapshot`

**Purpose:** Create or replace snapshot data for `/api/v2/system/{id64}/snapshot`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id64` | `path` | `true` | `integer` \| `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: [`SysSnapshot`](#schema-syssnapshot)

Example shape:

```json
{
  "v": 0,
  "rev": 0,
  "architect": "string",
  "id64": 0,
  "name": "string",
  "nickname": "string",
  "pos": [
    0
  ],
  "tierPoints": {
    "tier2": "...",
    "tier3": "..."
  },
  "sumEffects": {},
  "sites": [
    "..."
  ],
  "stale": true,
  "pop": {
    "pop": "...",
    "timeSpansh": "...",
    "timeSaved": "..."
  },
  "score": 0,
  "fav": true
}
```

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`Bod`](#schema-bod) |

### `GET /api/v2/system/snapshots`

**Purpose:** Retrieve snapshots data for `/api/v2/system/snapshots`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`SysSnapshot`](#schema-syssnapshot) |

### `GET /api/v2/system/{nameOrNum}/popHistory`

**Purpose:** Retrieve popHistory data for `/api/v2/system/{nameOrNum}/popHistory`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of [`History`](#schema-history) |

<a id="endpoints-without-declared-component-schemas"></a>

## Endpoints Without Declared Component Schemas

These endpoints either do not declare a body/response schema, or they only declare primitive values, arrays, or generic object maps rather than named component schemas.

## Cmdr

| Endpoint | Request Body | Main Response |
|---|---|---|
| `DELETE /api/Cmdr/{cmdr}` | — | — |
| `GET /api/Cmdr/{cmdr}/hiddenIDs` | — | array of `string` |
| `POST /api/Cmdr/{cmdr}/hiddenIDs` | array of `string` | array of `string` |
| `GET /api/Cmdr/{cmdr}/primary` | — | `string` |
| `DELETE /api/Cmdr/{cmdr}/primary` | — | — |
| `POST /api/Cmdr/{cmdr}/primary/{buildId}` | — | — |
| `PUT /api/Cmdr/{cmdr}/primary/{buildId}` | — | — |
| `GET /api/Cmdr/{cmdr}/assigned` | — | object/map of array of `string` |
| `GET /api/Cmdr/{cmdr}/assigned/active` | — | object/map of object/map of `integer` \| `string` |
| `DELETE /api/Cmdr/{cmdr}/fc/{marketId}` | — | — |
| `DELETE /api/Cmdr/currentShip` | — | array of `string` |
| `GET /api/Cmdr/chains` | — | object/map of `string` |

### `DELETE /api/Cmdr/{cmdr}`

**Purpose:** Delete/remove Cmdr data for `/api/Cmdr/{cmdr}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/Cmdr/{cmdr}/hiddenIDs`

**Purpose:** Retrieve hiddenIDs data for `/api/Cmdr/{cmdr}/hiddenIDs`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of `string` |

### `POST /api/Cmdr/{cmdr}/hiddenIDs`

**Purpose:** Submit/update hiddenIDs data for `/api/Cmdr/{cmdr}/hiddenIDs`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** Client-confirmed by RavenColonialWeb and SrvSurvey. Body is a string array of build IDs.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of `string` |

### `GET /api/Cmdr/{cmdr}/primary`

**Purpose:** Retrieve primary data for `/api/Cmdr/{cmdr}/primary`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | `string` |

### `DELETE /api/Cmdr/{cmdr}/primary`

**Purpose:** Delete/remove primary data for `/api/Cmdr/{cmdr}/primary`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb and SrvSurvey.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `POST /api/Cmdr/{cmdr}/primary/{buildId}`

**Purpose:** Submit/update primary data for `/api/Cmdr/{cmdr}/primary/{buildId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `PUT /api/Cmdr/{cmdr}/primary/{buildId}`

**Purpose:** Create or replace primary data for `/api/Cmdr/{cmdr}/primary/{buildId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb and SrvSurvey.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/Cmdr/{cmdr}/assigned`

**Purpose:** Retrieve assigned data for `/api/Cmdr/{cmdr}/assigned`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of array of `string` |

### `GET /api/Cmdr/{cmdr}/assigned/active`

**Purpose:** Retrieve active data for `/api/Cmdr/{cmdr}/assigned/active`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of object/map of `integer` \| `string` |

### `DELETE /api/Cmdr/{cmdr}/fc/{marketId}`

**Purpose:** Delete/remove fc data for `/api/Cmdr/{cmdr}/fc/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `cmdr` | `path` | `true` | `string` | — |
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `DELETE /api/Cmdr/currentShip`

**Purpose:** Delete/remove currentShip data for `/api/Cmdr/currentShip`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of `string` |

### `GET /api/Cmdr/chains`

**Purpose:** Retrieve chains data for `/api/Cmdr/chains`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `string` |

## FC

| Endpoint | Request Body | Main Response |
|---|---|---|
| `GET /api/FC/match/{name}` | — | object/map of `string` |
| `DELETE /api/FC/{marketId}` | — | — |
| `GET /api/FC/{marketId}/cargo` | — | — |
| `POST /api/FC/{marketId}/cargo` | object/map of `integer` \| `string` | object/map of `integer` \| `string` |
| `PATCH /api/FC/{marketId}/cargo` | object/map of `integer` \| `string` | object/map of `integer` \| `string` |
| `POST /api/FC/{nameOrNum}/location/{systemName}` | — | object/map of `integer` \| `string` |

### `GET /api/FC/match/{name}`

**Purpose:** Retrieve match data for `/api/FC/match/{name}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `name` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `string` |

### `DELETE /api/FC/{marketId}`

**Purpose:** Delete/remove FC data for `/api/FC/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/FC/{marketId}/cargo`

**Purpose:** Retrieve cargo data for `/api/FC/{marketId}/cargo`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `POST /api/FC/{marketId}/cargo`

**Purpose:** Submit/update cargo data for `/api/FC/{marketId}/cargo`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: object/map of `integer` | `string`

**Body confidence:** Client-confirmed by RavenColonialWeb `fc.updateCargo` and SrvSurvey `updateCargoFC`. Body is `Cargo`, a commodity-to-number map. Semantics: replace existing amounts for mentioned commodities.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `integer` \| `string` |

### `PATCH /api/FC/{marketId}/cargo`

**Purpose:** Partially update cargo data for `/api/FC/{marketId}/cargo`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: object/map of `integer` | `string`

**Body confidence:** Client-confirmed by RavenColonialWeb `fc.deliverToFC` and SrvSurvey `supplyFC`. Body is `Cargo`, a commodity-to-number delta map.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `integer` \| `string` |

### `POST /api/FC/{nameOrNum}/location/{systemName}`

**Purpose:** Submit/update location data for `/api/FC/{nameOrNum}/location/{systemName}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |
| `systemName` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb `fc.setLocation`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `integer` \| `string` |

## GGG

| Endpoint | Request Body | Main Response |
|---|---|---|
| `GET /api/GGG/csv` | — | array of `string` |

### `GET /api/GGG/csv`

**Purpose:** Retrieve csv data for `/api/GGG/csv`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of `string` |

## Misc

| Endpoint | Request Body | Main Response |
|---|---|---|
| `POST /api/login/reset` | — | — |
| `GET /api/stats` | — | `object` |
| `GET /api/misc/slotPredictionMismatches` | — | — |
| `GET /api/stats/sectorBuildCounts` | — | `object` |

### `POST /api/login/reset`

**Purpose:** Submit/update reset data for `/api/login/reset`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/stats`

**Purpose:** Retrieve stats data for `/api/stats`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | `object` |

### `GET /api/misc/slotPredictionMismatches`

**Purpose:** Retrieve slotPredictionMismatches data for `/api/misc/slotPredictionMismatches`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/stats/sectorBuildCounts`

**Purpose:** Retrieve sectorBuildCounts data for `/api/stats/sectorBuildCounts`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | `object` |

## Project

| Endpoint | Request Body | Main Response |
|---|---|---|
| `DELETE /api/project/{buildId}` | — | — |
| `PUT /api/project/{buildId}/link/{cmdr}` | — | — |
| `DELETE /api/project/{buildId}/link/{cmdr}` | — | — |
| `DELETE /api/project/{buildId}/fc/{marketId}` | — | — |
| `GET /api/project/{buildId}/fc` | — | object/map of object/map of `integer` \| `string` |
| `PUT /api/project/{buildId}/assign/{cmdr}/{commodity}` | — | — |
| `DELETE /api/project/{buildId}/assign/{cmdr}/{commodity}` | — | — |
| `POST /api/project/{buildId}/supply/{cmdr}` | `Cargo` — subtracts from need, then contributes | object/map of `integer` \| `string` |
| `PUT /api/project/{buildId}/supply/{cmdr}` | `Cargo` | object/map of `integer` \| `string` |
| `POST /api/system/{id64}/{marketId}/contribute/{cmdr}` | `Cargo` delta — history only | — |
| `POST /api/project/{buildId}/contribute/{cmdr}` | `Cargo` delta — history only | — |
| `POST /api/project/poll` | array of `string` | object/map of `string` (`date-time`) |
| `GET /api/project/{buildId}/last` | — | `string` (`date-time`) |
| `POST /api/project/{buildId}/complete` | — | — |
| `POST /api/system/{id64}/{marketId}/complete` | — | — |
| `POST /api/project/{buildId}/ready` | array of `string` | — |
| `PUT /api/project/{buildId}/ready` | array of `string` | — |
| `DELETE /api/project/{buildId}/ready` | array of `string` | — |

### `DELETE /api/project/{buildId}`

**Purpose:** Delete/remove project data for `/api/project/{buildId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `PUT /api/project/{buildId}/link/{cmdr}`

**Purpose:** Create or replace link data for `/api/project/{buildId}/link/{cmdr}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb and SrvSurvey.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `DELETE /api/project/{buildId}/link/{cmdr}`

**Purpose:** Delete/remove link data for `/api/project/{buildId}/link/{cmdr}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb and SrvSurvey.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `DELETE /api/project/{buildId}/fc/{marketId}`

**Purpose:** Delete/remove fc data for `/api/project/{buildId}/fc/{marketId}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb `project.unlinkFC`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/project/{buildId}/fc`

**Purpose:** Retrieve fc data for `/api/project/{buildId}/fc`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of object/map of `integer` \| `string` |

### `PUT /api/project/{buildId}/assign/{cmdr}/{commodity}`

**Purpose:** Create or replace {cmdr} data for `/api/project/{buildId}/assign/{cmdr}/{commodity}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `cmdr` | `path` | `true` | `string` | — |
| `commodity` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb and SrvSurvey.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `DELETE /api/project/{buildId}/assign/{cmdr}/{commodity}`

**Purpose:** Delete/remove {cmdr} data for `/api/project/{buildId}/assign/{cmdr}/{commodity}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `cmdr` | `path` | `true` | `string` | — |
| `commodity` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb and SrvSurvey.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `POST /api/project/{buildId}/supply/{cmdr}`

**Purpose:** **Non-journal “deliver to site”** — applies a delivery in one step: **subtract** each commodity amount in the body from the project’s stored remaining need, then record the same amounts as a commander contribution. Used by the Ravencolonial web client (`deliverToSite`). **Do not combine** with depot-driven **`PATCH`** updates for the same delivery, or remaining need can be reduced twice.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: object/map of `integer` | `string`

**Body confidence:** Client-confirmed by RavenColonialWeb `project.deliverToSite`. Body is `Cargo`, a commodity-to-quantity map (amounts **subtracted** from remaining need, then contributed).

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `integer` \| `string` |

### `PUT /api/project/{buildId}/supply/{cmdr}`

**Purpose:** Create or replace supply data for `/api/project/{buildId}/supply/{cmdr}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: object/map of `integer` | `string`

**Body confidence:** OpenAPI-declared shape only. Body is `Cargo`, but this exact method was not observed in the inspected clients.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `integer` \| `string` |

### `POST /api/system/{id64}/{marketId}/contribute/{cmdr}`

**Purpose:** Submit/update contribute data for `/api/system/{id64}/{marketId}/contribute/{cmdr}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id64` | `path` | `true` | `integer` \| `string` | — |
| `marketId` | `path` | `true` | `integer` \| `string` | — |
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: object/map of `integer` | `string`

**Body confidence:** OpenAPI-declared shape; likely same cargo-map semantics as project contribution.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `POST /api/project/{buildId}/contribute/{cmdr}`

**Purpose:** Record **commander-attributed delivery history** only. Adds rows to the contribution ledger; does **not** change project remaining need. Journal-aware clients (RavenColonial EDMC) call this on **`ColonisationContribution`** while syncing need separately via **`PATCH`** + **`colonisationConstructionDepot`**.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |
| `cmdr` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: object/map of `integer` | `string`

**Body confidence:** SrvSurvey-confirmed by `contribute`; RavenColonial EDMC uses the same route. Body is a `Dictionary<string,int>` / Cargo **delta** map (positive delivered counts). **`CargoDepot`** deliveries do not call this route — the depot journal line updates need; **`ColonisationContribution`** is the attribution event.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `POST /api/project/poll`

**Purpose:** Submit/update poll data for `/api/project/poll`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** Client-confirmed by RavenColonialWeb `project.poll`. Body is a string array of build IDs.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `string` (`date-time`) |

### `GET /api/project/{buildId}/last`

**Purpose:** Retrieve last data for `/api/project/{buildId}/last`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | `string` (`date-time`) |

### `POST /api/project/{buildId}/complete`

**Purpose:** Submit/update complete data for `/api/project/{buildId}/complete`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

None declared.

**Body confidence:** Client-confirmed bodyless by RavenColonialWeb and SrvSurvey.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `POST /api/system/{id64}/{marketId}/complete`

**Purpose:** Submit/update complete data for `/api/system/{id64}/{marketId}/complete`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id64` | `path` | `true` | `integer` \| `string` | — |
| `marketId` | `path` | `true` | `integer` \| `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `POST /api/project/{buildId}/ready`

**Purpose:** Submit/update ready data for `/api/project/{buildId}/ready`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** Client-confirmed by RavenColonialWeb `project.setReady`. Body is a string array of commodity names.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `PUT /api/project/{buildId}/ready`

**Purpose:** Create or replace ready data for `/api/project/{buildId}/ready`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** OpenAPI-declared shape only. Body is a string array of commodity names; this exact method was not observed in the inspected clients.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `DELETE /api/project/{buildId}/ready`

**Purpose:** Delete/remove ready data for `/api/project/{buildId}/ready`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `buildId` | `path` | `true` | `string` | — |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: array of `string`

Example shape:

```json
[
  "string"
]
```

**Body confidence:** Client-confirmed by RavenColonialWeb `project.setReady`. Body is a string array of commodity names.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

## Quest

| Endpoint | Request Body | Main Response |
|---|---|---|
| `POST /api/Quest/load` | — | — |

### `POST /api/Quest/load`

**Purpose:** Submit/update load data for `/api/Quest/load`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

**Body confidence:** SrvSurvey-confirmed bodyless; auth key is sent as a header.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

## System2

| Endpoint | Request Body | Main Response |
|---|---|---|
| `DELETE /api/v2/system/{nameOrNum}/!{saveName}` | — | — |
| `GET /api/v2/system/{nameOrNum}/architect` | — | `string` |
| `POST /api/v2/system/{id64}/fav/{fav}` | — | array of `integer` \| `string` |
| `GET /api/v2/system/revs` | — | object/map of `integer` \| `string` |
| `POST /api/v2/system/{nameOrNum}/refreshPop` | — | `string` |
| `PATCH /api/v2/system/{nameOrNum}/sites/{siteId}` | partial `Site` repair fields (`marketId`, `name`) | object or empty response |

### `PATCH /api/v2/system/{nameOrNum}/sites/{siteId}`

**Purpose:** Targeted site-row repair for `/api/v2/system/{nameOrNum}/sites/{siteId}`. RavenColonial EDMC uses this when a known v2 system site row needs a small correction, such as attaching a `marketId` or repairing a station/site display `name`, without replacing the full system site list.

**Authentication:** Requires the `rcc-key` header.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | System name or numeric system address. |
| `siteId` | `path` | `true` | `string` | v2 site row ID. Path-encoded by the client, so IDs such as `&4310842115` are sent as `%264310842115`. |

#### Request body

Required: `true`

Content types: `application/json`, `text/json`, `application/*+json`

Schema: partial [`Site`](#schema-site) repair fields. Client-confirmed fields:

| Field | Type | Notes |
|---|---|---|
| `marketId` | `integer` | Associates the site row with the station/carrier market ID. |
| `name` | `string` | Repairs the site display name. |

Example shapes:

```json
{
  "marketId": 4310555555
}
```

```json
{
  "name": "Dampier Gateway"
}
```

**Body confidence:** RavenColonial EDMC client-confirmed by `RavencolonialAPIClient.patch_system_site`. This route is used for targeted repairs; it is not a replacement for `PUT /api/v2/system/{nameOrNum}/sites`.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object or empty response |

### `DELETE /api/v2/system/{nameOrNum}/!{saveName}`

**Purpose:** Delete/remove {nameOrNum} data for `/api/v2/system/{nameOrNum}/!{saveName}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |
| `saveName` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | — | — |

### `GET /api/v2/system/{nameOrNum}/architect`

**Purpose:** Retrieve architect data for `/api/v2/system/{nameOrNum}/architect`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | `string` |

### `POST /api/v2/system/{id64}/fav/{fav}`

**Purpose:** Submit/update fav data for `/api/v2/system/{id64}/fav/{fav}`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `id64` | `path` | `true` | `integer` \| `string` | — |
| `fav` | `path` | `true` | `boolean` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | array of `integer` \| `string` |

### `GET /api/v2/system/revs`

**Purpose:** Retrieve revs data for `/api/v2/system/revs`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

None declared.

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | object/map of `integer` \| `string` |

### `POST /api/v2/system/{nameOrNum}/refreshPop`

**Purpose:** Submit/update refreshPop data for `/api/v2/system/{nameOrNum}/refreshPop`.

**Authentication:** Not specified in the OpenAPI document.

#### Parameters

| Name | In | Required | Type | Description |
|---|---|---:|---|---|
| `nameOrNum` | `path` | `true` | `string` | — |

#### Request body

None declared.

#### Responses

| Status | Description | Content types | Schema |
|---:|---|---|---|
| `200` | OK | `text/plain`, `application/json`, `text/json` | `string` |

<a id="schema-appendix"></a>

## Schema Appendix

The OpenAPI document defines 57 component schema(s).

### Schema: `Bod`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `name` | `true` | `string` | — |
| `num` | `true` | `integer` \| `string` | — |
| `distLS` | `true` | `number` \| `string` | — |
| `parents` | `true` | array of `integer` \| `string` | — |
| `type` | `true` | [`BodyType`](#schema-bodytype) | — |
| `subType` | `false` | `string` / `null` | — |
| `features` | `true` | array of [`BodyFeature`](#schema-bodyfeature) | — |
| `radius` | `false` | `number` \| `string` | — |
| `temp` | `false` | `number` \| `string` | — |
| `gravity` | `false` | `number` \| `string` | — |

Example shape:

```json
{
  "name": "string",
  "num": 0,
  "distLS": 0,
  "parents": [
    0
  ],
  "type": "un",
  "subType": "string",
  "features": [
    "bio"
  ],
  "radius": 0,
  "temp": 0,
  "gravity": 0
}
```

### Schema: `BodyFeature`

Type: `any` enum: `bio`, `geo`, `rings`, `volcanism`, `terraformable`, `tidal`, `landable`, `atmosphere`

Values: `bio`, `geo`, `rings`, `volcanism`, `terraformable`, `tidal`, `landable`, `atmosphere`

### Schema: `BodyType`

Type: `any` enum: `un`, `bh`, `ns`, `wd`, `st`, `aw`, `elw`, `gg`, `hmc`, `ib`, `mrb`, `rb`, `ri`, `wg`, `ww`, `ac`, `bc`

Values: `un`, `bh`, `ns`, `wd`, `st`, `aw`, `elw`, `gg`, `hmc`, `ib`, `mrb`, `rb`, `ri`, `wg`, `ww`, `ac`, `bc`

### Schema: `Category`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `name` | `true` | `string` | — |
| `color` | `true` | `string` / `null` | — |

Example shape:

```json
{
  "name": "string",
  "color": "string"
}
```

### Schema: `Chain`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `id` | `true` | `string` | — |
| `name` | `true` | `string` | — |
| `open` | `false` | `boolean` | — |
| `cmdrs` | `false` | array of `string` | — |
| `owner` | `true` | `string` | — |
| `fcs` | `false` | array of [`FleetCarrierView`](#schema-fleetcarrierview) | — |
| `systems` | `false` | array of [`Sys`](#schema-sys) | — |
| `hubs` | `false` | array of `integer` \| `string` | — |
| `notes` | `false` | `string` / `null` | — |

Example shape:

```json
{
  "id": "string",
  "name": "string",
  "open": true,
  "cmdrs": [
    "string"
  ],
  "owner": "string",
  "fcs": [
    {
      "marketId": "...",
      "name": "...",
      "displayName": "...",
      "owner": "...",
      "cargo": "...",
      "systemName": "...",
      "id64": "...",
      "starPos": "..."
    }
  ],
  "systems": [
    {
      "id64": "...",
      "name": "...",
      "nickname": "...",
      "pos": "...",
      "type": "...",
      "total": "...",
      "progress": "...",
      "needs": "...",
      "fcs": "...",
      "builds": "...",
      "buildTypes": "..."
    }
  ],
  "hubs": [
    0
  ],
  "notes": "string"
}
```

### Schema: `ChainCreate`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `name` | `true` | `string` | — |

Example shape:

```json
{
  "name": "string"
}
```

### Schema: `CmdrShip`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `cmdr` | `true` | `string` | — |
| `name` | `true` | `string` | — |
| `type` | `true` | `string` | — |
| `time` | `false` | `string` / `null` | — |
| `maxCargo` | `true` | `integer` \| `string` | — |
| `cargo` | `true` | object/map of `integer` \| `string` | — |

Example shape:

```json
{
  "cmdr": "string",
  "name": "string",
  "type": "string",
  "time": "2026-05-01T00:00:00Z",
  "maxCargo": 0,
  "cargo": {}
}
```

### Schema: `ColonisationConstructionDepot`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `timestamp` | `true` | `string` | — |
| `event` | `true` | `string` | — |
| `marketID` | `true` | `integer` \| `string` | — |
| `constructionProgress` | `true` | `number` \| `string` | — |
| `constructionComplete` | `true` | `boolean` | — |
| `constructionFailed` | `true` | `boolean` | — |
| `resourcesRequired` | `true` | array of [`ResourceRequired`](#schema-resourcerequired) | — |

Example shape:

```json
{
  "timestamp": "string",
  "event": "string",
  "marketID": 0,
  "constructionProgress": 0,
  "constructionComplete": true,
  "constructionFailed": true,
  "resourcesRequired": [
    {
      "name": "...",
      "name_Localised": "...",
      "requiredAmount": "...",
      "providedAmount": "...",
      "payment": "..."
    }
  ]
}
```

### Schema: `ColonyCost2`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `buildType` | `true` | `string` | — |
| `category` | `true` | `string` | — |
| `tier` | `false` | `integer` \| `string` | — |
| `location` | `true` | `string` | — |
| `displayName` | `true` | `string` | — |
| `displayName2` | `true` | `string` | — |
| `layouts` | `true` | array of `string` | — |
| `cargo` | `true` | object/map of `integer` \| `string` | — |

Example shape:

```json
{
  "buildType": "string",
  "category": "string",
  "tier": 0,
  "location": "string",
  "displayName": "string",
  "displayName2": "string",
  "layouts": [
    "string"
  ],
  "cargo": {}
}
```

### Schema: `CommanderPatch`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `displayName` | `false` | `string` / `null` | — |

Example shape:

```json
{
  "displayName": "string"
}
```

### Schema: `CommanderView`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `displayName` | `true` | `string` | — |

Example shape:

```json
{
  "displayName": "string"
}
```

### Schema: `Coord`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `x` | `true` | `number` \| `string` | — |
| `y` | `true` | `number` \| `string` | — |
| `z` | `true` | `number` \| `string` | — |

Example shape:

```json
{
  "x": 0,
  "y": 0,
  "z": 0
}
```

### Schema: `CreateGGG`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `cmdr` | `true` | `string` | — |
| `tag` | `true` | `string` | — |
| `starPos` | `true` | array of `number` \| `string` | — |
| `json` | `true` | `string` | — |

Example shape:

```json
{
  "cmdr": "string",
  "tag": "string",
  "starPos": [
    0
  ],
  "json": "string"
}
```

### Schema: `DefMsg`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `id` | `true` | `string` | — |
| `from` | `true` | `string` | — |
| `subject` | `false` | `string` / `null` | — |
| `body` | `true` | `string` | — |
| `actions` | `false` | `object` / `null` | — |

Example shape:

```json
{
  "id": "string",
  "from": "string",
  "subject": "string",
  "body": "string",
  "actions": {}
}
```

### Schema: `ETag`

Type: `any`

No properties declared.

### Schema: `Event`

Type: `any` enum: `pop`, `build`

Values: `pop`, `build`

### Schema: `FeedbackBody`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `subject` | `true` | `string` | — |
| `contact` | `false` | `string` / `null` | — |
| `message` | `true` | `string` | — |
| `images` | `false` | `array` / `null` | — |

Example shape:

```json
{
  "subject": "string",
  "contact": "string",
  "message": "string",
  "images": [
    "string"
  ]
}
```

### Schema: `FindMarketsOptions`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `refSystem` | `false` | `string` / `null` | — |
| `maxDistance` | `false` | `integer` \| `string` | — |
| `maxArrival` | `false` | `integer` \| `string` | — |
| `shipSize` | `true` | `string` | — |
| `noSurface` | `false` | `boolean` | — |
| `noFC` | `false` | `boolean` | — |
| `requireNeed` | `false` | `boolean` | — |
| `hasShipyard` | `false` | `boolean` | — |
| `commodities` | `false` | `object` / `null` | — |
| `buildIds` | `false` | `array` / `null` | — |

Example shape:

```json
{
  "refSystem": "string",
  "maxDistance": 0,
  "maxArrival": 0,
  "shipSize": "string",
  "noSurface": true,
  "noFC": true,
  "requireNeed": true,
  "hasShipyard": true,
  "commodities": {},
  "buildIds": [
    "string"
  ]
}
```

### Schema: `FleetCarrierPatch`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `displayName` | `false` | `string` / `null` | — |

Example shape:

```json
{
  "displayName": "string"
}
```

### Schema: `FleetCarrierView`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `marketId` | `false` | `integer` \| `string` | — |
| `name` | `true` | `string` | — |
| `displayName` | `true` | `string` | — |
| `owner` | `false` | `string` / `null` | — |
| `cargo` | `true` | object/map of `integer` \| `string` | — |
| `systemName` | `false` | `string` / `null` | — |
| `id64` | `false` | `integer` \| `string` / `null` | — |
| `starPos` | `false` | `array` / `null` | — |

Example shape:

```json
{
  "marketId": 0,
  "name": "string",
  "displayName": "string",
  "owner": "string",
  "cargo": {},
  "systemName": "string",
  "id64": 0,
  "starPos": [
    0
  ]
}
```

### Schema: `FoundMarkets`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `preparedAt` | `true` | `string` (`date-time`) | — |
| `buildId` | `true` | `string` | — |
| `systemName` | `true` | `string` | — |
| `commodities` | `false` | `object` / `null` | — |
| `markets` | `true` | array of [`MarketSummary`](#schema-marketsummary) | — |

Example shape:

```json
{
  "preparedAt": "2026-05-01T00:00:00Z",
  "buildId": "string",
  "systemName": "string",
  "commodities": {},
  "markets": [
    {
      "marketId": "...",
      "stationName": "...",
      "type": "...",
      "economy": "...",
      "economies": "...",
      "updatedAt": "...",
      "supplies": "...",
      "surface": "...",
      "padSize": "...",
      "bodyName": "...",
      "systemName": "...",
      "distance": "...",
      "distanceToArrival": "...",
      "starPos": "..."
    }
  ]
}
```

### Schema: `GGG`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `timeScan` | `true` | `string` | — |
| `id64` | `true` | `integer` \| `string` | — |
| `systemName` | `true` | `string` | — |
| `bodyName` | `true` | `string` | — |
| `bodyID` | `true` | `integer` \| `string` | — |
| `surfaceTemp` | `true` | `number` \| `string` | — |
| `cmdr` | `true` | `string` | — |
| `tag` | `true` | `string` | — |
| `starPos` | `true` | array of `number` \| `string` | — |
| `journalJson` | `true` | `string` | — |

Example shape:

```json
{
  "timeScan": "string",
  "id64": 0,
  "systemName": "string",
  "bodyName": "string",
  "bodyID": 0,
  "surfaceTemp": 0,
  "cmdr": "string",
  "tag": "string",
  "starPos": [
    0
  ],
  "journalJson": "string"
}
```

### Schema: `GetRealEconomies`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `id` | `true` | `integer` \| `string` | — |
| `updated` | `true` | `string` | — |
| `economies` | `true` | object/map of `number` \| `string` | — |

Example shape:

```json
{
  "id": 0,
  "updated": "string",
  "economies": {}
}
```

### Schema: `History`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `time` | `false` | `string` (`date-time`) | — |
| `event` | `true` | [`Event`](#schema-event) | — |
| `json` | `true` | `string` | — |

Example shape:

```json
{
  "time": "2026-05-01T00:00:00Z",
  "event": "pop",
  "json": "string"
}
```

### Schema: `JsonElement`

Type: `any`

No properties declared.

### Schema: `LoginBody`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `access_token` | `true` | `string` | — |
| `expires_in` | `true` | `integer` \| `string` | — |
| `refresh_token` | `true` | `string` | — |
| `token_type` | `true` | `string` | — |

Example shape:

```json
{
  "access_token": "string",
  "expires_in": 0,
  "refresh_token": "string",
  "token_type": "string"
}
```

### Schema: `MapData`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `categories` | `false` | `object` / `null` | — |
| `systems` | `false` | array of [`System`](#schema-system) | — |
| `routes` | `false` | `array` / `null` | — |

Example shape:

```json
{
  "categories": {},
  "systems": [
    {
      "name": "...",
      "coords": "...",
      "type": "...",
      "infos": "...",
      "cat": "..."
    }
  ],
  "routes": [
    {
      "title": "...",
      "points": "..."
    }
  ]
}
```

### Schema: `MarketSummary`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `marketId` | `true` | `integer` \| `string` | — |
| `stationName` | `true` | `string` | — |
| `type` | `false` | `string` / `null` | — |
| `economy` | `false` | `string` / `null` | — |
| `economies` | `false` | `object` / `null` | — |
| `updatedAt` | `true` | `string` | — |
| `supplies` | `true` | object/map of `integer` \| `string` | — |
| `surface` | `true` | `boolean` | — |
| `padSize` | `true` | `string` | — |
| `bodyName` | `false` | `string` / `null` | — |
| `systemName` | `true` | `string` | — |
| `distance` | `true` | `number` \| `string` | — |
| `distanceToArrival` | `true` | `number` \| `string` | — |
| `starPos` | `true` | array of `number` \| `string` | — |

Example shape:

```json
{
  "marketId": 0,
  "stationName": "string",
  "type": "string",
  "economy": "string",
  "economies": {},
  "updatedAt": "string",
  "supplies": {},
  "surface": true,
  "padSize": "string",
  "bodyName": "string",
  "systemName": "string",
  "distance": 0,
  "distanceToArrival": 0,
  "starPos": [
    0
  ]
}
```

### Schema: `MockMin`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `buildId` | `true` | `string` | — |
| `buildType` | `true` | `string` | — |
| `buildName` | `true` | `string` | — |
| `bodyName` | `true` | `string` | — |
| `timeCompleted` | `true` | `string` | — |
| `isPrimaryPort` | `true` | `boolean` | — |

Example shape:

```json
{
  "buildId": "string",
  "buildType": "string",
  "buildName": "string",
  "bodyName": "string",
  "timeCompleted": "string",
  "isPrimaryPort": true
}
```

### Schema: `MockMinPayload`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `etag` | `false` | [`ETag`](#schema-etag) | — |
| `mocks` | `true` | array of [`MockMin`](#schema-mockmin) | — |

Example shape:

```json
{
  "etag": null,
  "mocks": [
    {
      "buildId": "...",
      "buildType": "...",
      "buildName": "...",
      "bodyName": "...",
      "timeCompleted": "...",
      "isPrimaryPort": "..."
    }
  ]
}
```

### Schema: `Point`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `label` | `false` | `string` / `null` | — |
| `s` | `true` | `string` / `null` | — |
| `coords` | `false` | [`Coord`](#schema-coord) | — |

Example shape:

```json
{
  "label": "string",
  "s": "string",
  "coords": {
    "x": 0,
    "y": 0,
    "z": 0
  }
}
```

### Schema: `Pop`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `pop` | `true` | `integer` \| `string` | — |
| `timeSpansh` | `true` | `string` (`date-time`) | — |
| `timeSaved` | `true` | `string` (`date-time`) | — |

Example shape:

```json
{
  "pop": 0,
  "timeSpansh": "2026-05-01T00:00:00Z",
  "timeSaved": "2026-05-01T00:00:00Z"
}
```

### Schema: `ProjectCreate`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `marketId` | `true` | `integer` \| `string` | — |
| `systemAddress` | `true` | `integer` \| `string` | — |
| `buildName` | `true` | `string` | — |
| `systemSiteId` | `false` | `string` / `null` | — |
| `commodities` | `false` | `object` / `null` | — |
| `colonisationConstructionDepot` | `false` | [`ColonisationConstructionDepot`](#schema-colonisationconstructiondepot) | — |
| `buildType` | `false` | `string` / `null` | — |
| `systemName` | `false` | `string` / `null` | — |
| `starPos` | `false` | `array` / `null` | — |
| `bodyNum` | `false` | `integer` \| `string` / `null` | — |
| `bodyName` | `false` | `string` / `null` | — |
| `architectName` | `false` | `string` / `null` | — |
| `discordLink` | `false` | `string` / `null` | — |
| `timeDue` | `false` | `string` / `null` | — |
| `isPrimaryPort` | `false` | `boolean` | — |
| `commanders` | `false` | `object` / `null` | — |
| `notes` | `false` | `string` / `null` | — |
| `maxNeed` | `false` | `integer` \| `string` / `null` | — |
| `bodyType` | `false` | `string` / `null` | — |
| `bodyFeatures` | `false` | `array` / `null` | — |
| `systemFeatures` | `false` | `array` / `null` | — |
| `reserveLevel` | `false` | [`ReserveLevel`](#schema-reservelevel) | — |
| `prepBuilds` | `false` | `object` / `null` | — |

Example shape:

```json
{
  "marketId": 0,
  "systemAddress": 0,
  "buildName": "string",
  "systemSiteId": "string",
  "commodities": {},
  "colonisationConstructionDepot": {
    "timestamp": "string",
    "event": "string",
    "marketID": 0,
    "constructionProgress": 0,
    "constructionComplete": true,
    "constructionFailed": true,
    "resourcesRequired": [
      "..."
    ]
  },
  "buildType": "string",
  "systemName": "string",
  "starPos": [
    0
  ],
  "bodyNum": 0,
  "bodyName": "string",
  "architectName": "string",
  "discordLink": "string",
  "timeDue": "2026-05-01T00:00:00Z",
  "isPrimaryPort": true,
  "commanders": {},
  "notes": "string",
  "maxNeed": 0,
  "bodyType": "string",
  "bodyFeatures": [
    "bio"
  ]
}
```

### Schema: `ProjectFC`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `marketId` | `true` | `integer` \| `string` | — |
| `name` | `true` | `string` | — |
| `displayName` | `true` | `string` | — |
| `assign` | `true` | array of `string` | — |

Example shape:

```json
{
  "marketId": 0,
  "name": "string",
  "displayName": "string",
  "assign": [
    "string"
  ]
}
```

### Schema: `ProjectRef`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `timestamp` | `false` | `string` / `null` | — |
| `eTag` | `false` | [`ETag`](#schema-etag) | — |
| `buildId` | `true` | `string` | — |
| `buildType` | `true` | `string` | — |
| `buildName` | `true` | `string` | — |
| `marketId` | `false` | `integer` \| `string` | — |
| `systemAddress` | `false` | `integer` \| `string` | — |
| `systemName` | `true` | `string` | — |
| `starPos` | `true` | array of `number` \| `string` | — |
| `bodyNum` | `false` | `integer` \| `string` / `null` | — |
| `bodyName` | `false` | `string` / `null` | — |
| `factionName` | `false` | `string` / `null` | — |
| `architectName` | `false` | `string` / `null` | — |
| `maxNeed` | `false` | `integer` \| `string` | — |
| `complete` | `false` | `boolean` | — |
| `discordLink` | `false` | `string` / `null` | — |
| `timeDue` | `false` | `string` / `null` | — |
| `timeCompleted` | `false` | `string` / `null` | — |
| `timestarted` | `false` | `string` / `null` | — |
| `isPrimaryPort` | `false` | `boolean` | — |
| `bodyType` | `false` | `string` / `null` | — |
| `bodyFeatures` | `false` | `array` / `null` | — |
| `systemFeatures` | `false` | `array` / `null` | — |
| `reserveLevel` | `false` | [`ReserveLevel`](#schema-reservelevel) | — |

Example shape:

```json
{
  "timestamp": "2026-05-01T00:00:00Z",
  "eTag": null,
  "buildId": "string",
  "buildType": "string",
  "buildName": "string",
  "marketId": 0,
  "systemAddress": 0,
  "systemName": "string",
  "starPos": [
    0
  ],
  "bodyNum": 0,
  "bodyName": "string",
  "factionName": "string",
  "architectName": "string",
  "maxNeed": 0,
  "complete": true,
  "discordLink": "string",
  "timeDue": "2026-05-01T00:00:00Z",
  "timeCompleted": "2026-05-01T00:00:00Z",
  "timestarted": "2026-05-01T00:00:00Z",
  "isPrimaryPort": true
}
```

### Schema: `ProjectRefComplete`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `systemName` | `true` | `string` | — |
| `marketId` | `false` | `integer` \| `string` | — |
| `buildId` | `true` | `string` | — |
| `buildType` | `true` | `string` | — |
| `buildName` | `true` | `string` | — |

Example shape:

```json
{
  "systemName": "string",
  "marketId": 0,
  "buildId": "string",
  "buildType": "string",
  "buildName": "string"
}
```

### Schema: `ProjectUpdate`

Type: `object`

**Client semantics (not all in OpenAPI):** On **`PATCH`**, when **`colonisationConstructionDepot`** is present, **`commodities`** is the per-commodity **remaining need** map (typically `RequiredAmount − ProvidedAmount` from the journal, ≥ 0) and **`maxNeed`** is the sum of required amounts. Negative values in stored project **`commodities`** (e.g. template placeholders at `-1` after link) may render as **`?`** on the website until explicitly set to **`0`**.

| Property | Required | Type | Description |
|---|---:|---|---|
| `timestamp` | `false` | `string` / `null` | — |
| `eTag` | `false` | [`ETag`](#schema-etag) | — |
| `buildId` | `true` | `string` | — |
| `marketId` | `false` | `integer` \| `string` / `null` | — |
| `buildType` | `false` | `string` / `null` | — |
| `buildName` | `false` | `string` / `null` | — |
| `bodyNum` | `false` | `integer` \| `string` / `null` | — |
| `bodyName` | `false` | `string` / `null` | — |
| `factionName` | `false` | `string` / `null` | — |
| `architectName` | `false` | `string` / `null` | — |
| `discordLink` | `false` | `string` / `null` | — |
| `timeDue` | `false` | `string` / `null` | — |
| `timeCompleted` | `false` | `string` / `null` | — |
| `timeStarted` | `false` | `string` / `null` | — |
| `isPrimaryPort` | `false` | `boolean` / `null` | — |
| `notes` | `false` | `string` / `null` | — |
| `maxNeed` | `false` | `integer` \| `string` / `null` | — |
| `commodities` | `false` | `object` / `null` | — |
| `colonisationConstructionDepot` | `false` | [`ColonisationConstructionDepot`](#schema-colonisationconstructiondepot) | — |
| `bodyType` | `false` | `string` / `null` | — |
| `bodyFeatures` | `false` | `array` / `null` | — |
| `systemFeatures` | `false` | `array` / `null` | — |
| `reserveLevel` | `false` | [`ReserveLevel`](#schema-reservelevel) | — |
| `prepBuilds` | `false` | `object` / `null` | — |

Example shape:

```json
{
  "timestamp": "2026-05-01T00:00:00Z",
  "eTag": null,
  "buildId": "string",
  "marketId": 0,
  "buildType": "string",
  "buildName": "string",
  "bodyNum": 0,
  "bodyName": "string",
  "factionName": "string",
  "architectName": "string",
  "discordLink": "string",
  "timeDue": "string",
  "timeCompleted": "string",
  "timeStarted": "string",
  "isPrimaryPort": true,
  "notes": "string",
  "maxNeed": 0,
  "commodities": {},
  "colonisationConstructionDepot": {
    "timestamp": "string",
    "event": "string",
    "marketID": 0,
    "constructionProgress": 0,
    "constructionComplete": true,
    "constructionFailed": true,
    "resourcesRequired": [
      "..."
    ]
  },
  "bodyType": "string"
}
```

### Schema: `ProjectView`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `timestamp` | `false` | `string` / `null` | — |
| `eTag` | `false` | [`ETag`](#schema-etag) | — |
| `buildId` | `true` | `string` | — |
| `sumNeed` | `false` | `integer` \| `string` | — |
| `maxNeed` | `false` | `integer` \| `string` | — |
| `complete` | `false` | `boolean` | — |
| `commodities` | `true` | object/map of `integer` \| `string` | — |
| `ready` | `true` | array of `string` | — |
| `linkedFC` | `true` | array of [`ProjectFC`](#schema-projectfc) | — |
| `prepBuilds` | `false` | `object` / `null` | — |
| `buildType` | `true` | `string` | — |
| `buildName` | `true` | `string` | — |
| `marketId` | `false` | `integer` \| `string` | — |
| `systemAddress` | `false` | `integer` \| `string` | — |
| `systemName` | `true` | `string` | — |
| `starPos` | `true` | array of `number` \| `string` | — |
| `bodyNum` | `false` | `integer` \| `string` / `null` | — |
| `bodyName` | `false` | `string` / `null` | — |
| `factionName` | `false` | `string` / `null` | — |
| `architectName` | `false` | `string` / `null` | — |
| `discordLink` | `false` | `string` / `null` | — |
| `timeDue` | `false` | `string` / `null` | — |
| `timeCompleted` | `false` | `string` / `null` | — |
| `timestarted` | `false` | `string` / `null` | — |
| `isPrimaryPort` | `false` | `boolean` | — |
| `commanders` | `false` | `object` / `null` | — |
| `notes` | `false` | `string` / `null` | — |
| `bodyType` | `false` | `string` / `null` | — |
| `bodyFeatures` | `false` | `array` / `null` | — |
| `systemFeatures` | `false` | `array` / `null` | — |
| `reserveLevel` | `false` | [`ReserveLevel`](#schema-reservelevel) | — |

Example shape:

```json
{
  "timestamp": "2026-05-01T00:00:00Z",
  "eTag": null,
  "buildId": "string",
  "sumNeed": 0,
  "maxNeed": 0,
  "complete": true,
  "commodities": {},
  "ready": [
    "string"
  ],
  "linkedFC": [
    {
      "marketId": "...",
      "name": "...",
      "displayName": "...",
      "assign": "..."
    }
  ],
  "prepBuilds": {},
  "buildType": "string",
  "buildName": "string",
  "marketId": 0,
  "systemAddress": 0,
  "systemName": "string",
  "starPos": [
    0
  ],
  "bodyNum": 0,
  "bodyName": "string",
  "factionName": "string",
  "architectName": "string"
}
```

### Schema: `QuestDef`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `firstChapter` | `true` | `string` | — |
| `objectives` | `false` | object/map of `string` | — |
| `msgs` | `false` | array of [`DefMsg`](#schema-defmsg) | — |
| `chapters` | `false` | object/map of `string` | — |
| `id` | `true` | `string` | — |
| `ver` | `true` | `number` \| `string` | — |
| `publisher` | `true` | `string` | — |
| `title` | `true` | `string` | — |
| `desc` | `false` | `string` / `null` | — |

Example shape:

```json
{
  "firstChapter": "string",
  "objectives": {},
  "msgs": [
    {
      "id": "...",
      "from": "...",
      "subject": "...",
      "body": "...",
      "actions": "..."
    }
  ],
  "chapters": {},
  "id": "string",
  "ver": 0,
  "publisher": "string",
  "title": "string",
  "desc": "string"
}
```

### Schema: `QuestSummary`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `id` | `true` | `string` | — |
| `ver` | `true` | `number` \| `string` | — |
| `publisher` | `true` | `string` | — |
| `title` | `true` | `string` | — |
| `desc` | `false` | `string` / `null` | — |

Example shape:

```json
{
  "id": "string",
  "ver": 0,
  "publisher": "string",
  "title": "string",
  "desc": "string"
}
```

### Schema: `QuickSearchStation`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `market_id` | `true` | `integer` \| `string` | — |
| `name` | `true` | `string` | — |
| `carrier_name` | `false` | `string` / `null` | — |
| `system_id64` | `false` | `number` \| `string` | — |
| `system_x` | `false` | `number` \| `string` | — |
| `system_y` | `false` | `number` \| `string` | — |
| `system_z` | `false` | `number` \| `string` | — |

Example shape:

```json
{
  "market_id": 0,
  "name": "string",
  "carrier_name": "string",
  "system_id64": 0,
  "system_x": 0,
  "system_y": 0,
  "system_z": 0
}
```

### Schema: `ReserveLevel`

Type: `any` enum: `depleted`, `low`, `common`, `major`, `pristine`, `None`

Values: `depleted`, `low`, `common`, `major`, `pristine`, `None`

### Schema: `ResourceRequired`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `name` | `true` | `string` | — |
| `name_Localised` | `false` | `string` / `null` | — |
| `requiredAmount` | `true` | `integer` \| `string` | — |
| `providedAmount` | `true` | `integer` \| `string` | — |
| `payment` | `false` | `integer` \| `string` | — |

Example shape:

```json
{
  "name": "string",
  "name_Localised": "string",
  "requiredAmount": 0,
  "providedAmount": 0,
  "payment": 0
}
```

### Schema: `Route`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `title` | `true` | `string` | — |
| `points` | `true` | array of [`Point`](#schema-point) | — |

Example shape:

```json
{
  "title": "string",
  "points": [
    {
      "label": "...",
      "s": "...",
      "coords": "..."
    }
  ]
}
```

### Schema: `Site`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `id` | `true` | `string` | — |
| `name` | `true` | `string` | — |
| `bodyNum` | `true` | `integer` \| `string` | — |
| `buildType` | `false` | `string` / `null` | — |
| `status` | `false` | [`Status`](#schema-status) | — |
| `buildId` | `false` | `string` / `null` | — |
| `marketId` | `false` | `integer` \| `string` / `null` | — |

Example shape:

```json
{
  "id": "string",
  "name": "string",
  "bodyNum": 0,
  "buildType": "string",
  "status": "plan",
  "buildId": "string",
  "marketId": 0
}
```

### Schema: `SitesPut`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `update` | `true` | array of [`Site`](#schema-site) | — |
| `delete` | `true` | array of `string` | — |
| `orderIDs` | `false` | `array` / `null` | — |
| `architect` | `false` | `string` / `null` | — |
| `nickname` | `false` | `string` / `null` | — |
| `publish` | `false` | `boolean` / `null` | — |
| `notes` | `false` | `string` / `null` | — |
| `saveName` | `false` | `string` / `null` | — |
| `idxCalcLimit` | `false` | `integer` \| `string` / `null` | — |
| `open` | `false` | `boolean` / `null` | — |
| `reserveLevel` | `false` | [`ReserveLevel`](#schema-reservelevel) | — |
| `snapshot` | `false` | [`SysSnapshot`](#schema-syssnapshot) | — |
| `slots` | `false` | `object` / `null` | — |

Example shape:

```json
{
  "update": [
    {
      "id": "...",
      "name": "...",
      "bodyNum": "...",
      "buildType": "...",
      "status": "...",
      "buildId": "...",
      "marketId": "..."
    }
  ],
  "delete": [
    "string"
  ],
  "orderIDs": [
    "string"
  ],
  "architect": "string",
  "nickname": "string",
  "publish": true,
  "notes": "string",
  "saveName": "string",
  "idxCalcLimit": 0,
  "open": true,
  "reserveLevel": "depleted",
  "snapshot": {
    "v": 0,
    "rev": 0,
    "architect": "string",
    "id64": 0,
    "name": "string",
    "nickname": "string",
    "pos": [
      "..."
    ],
    "tierPoints": "...",
    "sumEffects": {},
    "sites": [
      "..."
    ],
    "stale": true,
    "pop": "...",
    "score": 0,
    "fav": true
  },
  "slots": {}
}
```

### Schema: `Status`

Type: `any` enum: `plan`, `build`, `complete`, `demolish`

Values: `plan`, `build`, `complete`, `demolish`

### Schema: `Summary`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `id` | `true` | `string` | — |
| `name` | `true` | `string` | — |
| `open` | `false` | `boolean` | — |
| `owner` | `true` | `string` | — |
| `destination` | `false` | `string` / `null` | — |

Example shape:

```json
{
  "id": "string",
  "name": "string",
  "open": true,
  "owner": "string",
  "destination": "string"
}
```

### Schema: `SupplyStats`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `time` | `false` | `string` (`date-time`) | — |
| `countCargo` | `false` | `integer` \| `string` | — |
| `countDeliveries` | `false` | `integer` \| `string` | — |
| `cmdrs` | `false` | object/map of `integer` \| `string` | — |

Example shape:

```json
{
  "time": "2026-05-01T00:00:00Z",
  "countCargo": 0,
  "countDeliveries": 0,
  "cmdrs": {}
}
```

### Schema: `SupplyStatsSummary`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `buildId` | `true` | `string` | — |
| `totalCargo` | `false` | `integer` \| `string` | — |
| `totalDeliveries` | `false` | `integer` \| `string` | — |
| `start` | `false` | `string` / `null` | — |
| `end` | `false` | `string` / `null` | — |
| `cmdrs` | `false` | object/map of `integer` \| `string` | — |
| `stats` | `false` | array of [`SupplyStats`](#schema-supplystats) | — |

Example shape:

```json
{
  "buildId": "string",
  "totalCargo": 0,
  "totalDeliveries": 0,
  "start": "2026-05-01T00:00:00Z",
  "end": "2026-05-01T00:00:00Z",
  "cmdrs": {},
  "stats": [
    {
      "time": "...",
      "countCargo": "...",
      "countDeliveries": "...",
      "cmdrs": "..."
    }
  ]
}
```

### Schema: `Sys`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `id64` | `true` | `integer` \| `string` | — |
| `name` | `true` | `string` | — |
| `nickname` | `false` | `string` / `null` | — |
| `pos` | `true` | array of `number` \| `string` | — |
| `type` | `false` | [`Type`](#schema-type) | — |
| `total` | `false` | `integer` \| `string` | — |
| `progress` | `false` | `integer` \| `string` | — |
| `needs` | `false` | `object` / `null` | — |
| `fcs` | `false` | `array` / `null` | — |
| `builds` | `false` | array of [`ProjectView`](#schema-projectview) | — |
| `buildTypes` | `false` | object/map of `integer` \| `string` | — |

Example shape:

```json
{
  "id64": 0,
  "name": "string",
  "nickname": "string",
  "pos": [
    0
  ],
  "type": "bridge",
  "total": 0,
  "progress": 0,
  "needs": {},
  "fcs": [
    0
  ],
  "builds": [
    {
      "timestamp": "...",
      "eTag": "...",
      "buildId": "...",
      "sumNeed": "...",
      "maxNeed": "...",
      "complete": "...",
      "commodities": "...",
      "ready": "...",
      "linkedFC": "...",
      "prepBuilds": "...",
      "buildType": "...",
      "buildName": "...",
      "marketId": "...",
      "systemAddress": "...",
      "systemName": "...",
      "starPos": "...",
      "bodyNum": "...",
      "bodyName": "...",
      "factionName": "...",
      "architectName": "..."
    }
  ],
  "buildTypes": {}
}
```

### Schema: `SysID64`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `id64` | `true` | `integer` \| `string` | — |
| `name` | `true` | `string` | — |
| `nickname` | `false` | `string` / `null` | — |
| `pos` | `true` | array of `number` \| `string` | — |

Example shape:

```json
{
  "id64": 0,
  "name": "string",
  "nickname": "string",
  "pos": [
    0
  ]
}
```

### Schema: `SysSnapshot`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `v` | `false` | `integer` \| `string` | — |
| `rev` | `false` | `integer` \| `string` | — |
| `architect` | `true` | `string` | — |
| `id64` | `true` | `integer` \| `string` | — |
| `name` | `true` | `string` | — |
| `nickname` | `false` | `string` / `null` | — |
| `pos` | `true` | array of `number` \| `string` | — |
| `tierPoints` | `true` | [`TierPoints`](#schema-tierpoints) | — |
| `sumEffects` | `true` | object/map of `number` \| `string` | — |
| `sites` | `true` | array of [`Site`](#schema-site) | — |
| `stale` | `false` | `boolean` | — |
| `pop` | `false` | [`Pop`](#schema-pop) | — |
| `score` | `false` | `integer` \| `string` | — |
| `fav` | `false` | `boolean` / `null` | — |

Example shape:

```json
{
  "v": 0,
  "rev": 0,
  "architect": "string",
  "id64": 0,
  "name": "string",
  "nickname": "string",
  "pos": [
    0
  ],
  "tierPoints": {
    "tier2": 0,
    "tier3": 0
  },
  "sumEffects": {},
  "sites": [
    {
      "id": "...",
      "name": "...",
      "bodyNum": "...",
      "buildType": "...",
      "status": "...",
      "buildId": "...",
      "marketId": "..."
    }
  ],
  "stale": true,
  "pop": {
    "pop": 0,
    "timeSpansh": "2026-05-01T00:00:00Z",
    "timeSaved": "2026-05-01T00:00:00Z"
  },
  "score": 0,
  "fav": true
}
```

### Schema: `System`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `name` | `true` | `string` | — |
| `coords` | `true` | [`Coord`](#schema-coord) | — |
| `type` | `false` | `integer` \| `string` / `null` | — |
| `infos` | `false` | `string` / `null` | — |
| `cat` | `false` | `array` / `null` | — |

Example shape:

```json
{
  "name": "string",
  "coords": {
    "x": 0,
    "y": 0,
    "z": 0
  },
  "type": 0,
  "infos": "string",
  "cat": [
    0
  ]
}
```

### Schema: `SystemFeature`

Type: `any` enum: `blackHole`, `whiteDwarf`, `neutronStar`

Values: `blackHole`, `whiteDwarf`, `neutronStar`

### Schema: `TierPoints`

Type: `object`

| Property | Required | Type | Description |
|---|---:|---|---|
| `tier2` | `true` | `integer` \| `string` | — |
| `tier3` | `true` | `integer` \| `string` | — |

Example shape:

```json
{
  "tier2": 0,
  "tier3": 0
}
```

### Schema: `Type`

Type: `any` enum: `bridge`, `hub`

Values: `bridge`, `hub`
