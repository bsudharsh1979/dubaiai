# Integration and access requirements

Nothing in this list is connected. Every item below is shown in the Assurance view as **"requires authorized access"**
or **"simulated"**. No endpoints were invented and no protected service was scraped.

| Source / system | Role in RainReady | What authorization would be required | How the prototype stands in for it |
|---|---|---|---|
| **NCM (National Center of Meteorology)** nowcasts, radar, gauge network | `forecast_risk` label, rainfall intensity for the twin | Formal data-sharing agreement; machine-readable feed specification (issue/valid times, units, grid/CRS); SLA for latency | Synthetic `Forecast` rows with `issued_at`/`valid_at`; replay respects `available_at` |
| Municipal drainage telemetry (water levels, pump status) | `observed_water`, pump availability | Authority telemetry access, tag list, units, quality flags, historian export for replay | Synthetic sensors `WL-U7`, PS7 state in scenario controls |
| Utility SCADA / DMA metering (flow, pressure) | `anomaly` label for leaks | Utility agreement; DMA boundaries; baseline night-flow history; maintenance/flushing schedule feed | Synthetic `FM-12`/`PM-12`, planned-flushing record in scenario B2 |
| **Copernicus Sentinel-1 GRD/RTC** | `observed_water` candidate inundation | Copernicus Data Space account (free, licence acceptance); processing chain (orbit file, thermal noise, calibration, terrain correction) or an RTC provider; same relative orbit for before/after pairs | Synthetic pair with the same validation path (`/api/imports/sentinel1` accepts real GeoTIFFs with sidecar metadata) |
| **Sentinel-2 / optical** | Context, cloud-permitting | Copernicus Data Space; cloud masking | Synthetic optical scene with `cloud_fraction=0.72` (used as low-quality evidence in scenario C) |
| High-resolution DEM / drainage network GIS | Susceptibility, catchment delineation, storage curves | Municipal GIS licence; survey-grade DEM; asset register with criticality | Hand-authored catchments and asset list (`susceptibility` label derived from fixtures) |
| Road network and closures (transport authority) | Routing exclusions, closures as actions | Authority feed for live closures; routing graph licence | Sector road graph with synthetic closures |
| Asset register (hospitals, schools, substations, worksites) | Exposure overlay, HSE consequence | Owner agreements; occupancy data | Synthetic assets with criticality |
| Field workforce app / 112 / call centre | Field reports, casualty mentions | Integration agreement; identity federation; content policy | Built-in field report form with photo upload |
| Dispatch / CAD / work-order systems | Action execution | **Deliberately not implemented**; would require an agency-owned adapter with its own approval and audit; RainReady only emits approved, hash-bound requests | Simulated receipts |
| Identity (SSO/OIDC, UAE PASS or agency IdP) | Server-side identity and roles | IdP registration; role mapping agreed with each department | Demo login (`DEMO_AUTH=true`) with server-assigned roles |
| Model serving (NVIDIA NIM on sovereign GPUs) | Text/tool-use, embeddings, guards | GPU capacity in-country; NIM licence; model licence review; `/v1/models` exposure | `MODEL_PROVIDER=demo`; `local_nim` adapter implemented |

## Minimum data contracts RainReady expects

* Every observation: `source_id`, `observed_at`, `available_at`, geometry + CRS, units, quality flags, provenance URI,
  checksum, licence class.
* Forecasts: additionally `issued_at`, `valid_at`, model/run identifier.
* Rasters: GeoTIFF with CRS, nodata, units tag, acquisition time, orbit/polarisation sidecar.
* All timestamps in UTC.

## Licensing notes

Copernicus data is free and open under the Copernicus Sentinel Data Terms; derived products should credit
"Contains modified Copernicus Sentinel data [year]". Government telemetry, GIS and asset registers are typically
restricted; RainReady's `license_class` field and sovereign mode exist so that such data never leaves the deployment.
