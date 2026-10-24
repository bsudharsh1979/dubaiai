"use client";
import * as maplibregl from "maplibre-gl";
import type { Map as MLMap, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type FC = GeoJSON.FeatureCollection;
export type Basemap = {
  attribution: string;
  center: [number, number];
  zoom: number;
  assets: FC;
  catchments: FC;
  roads: FC;
  sensors: FC;
  scene_candidates: FC;
  sector: GeoJSON.Feature;
};

export type Overlay = {
  /** incident/hazard polygons to highlight */
  hazard?: GeoJSON.Feature | GeoJSON.FeatureCollection | null;
  /** candidate route as LineString */
  route?: GeoJSON.Feature | null;
  /** per-catchment band for colouring */
  bands?: Record<string, string>;
  /** sensor ids flagged as outage */
  sensorOutage?: string[];
  /** road link ids closed/flooded */
  closedRoads?: string[];
};

const BAND_COLOR: Record<string, string> = { low: "#2f9e6b", moderate: "#d9a521", high: "#e2711d", severe: "#b42318", unknown: "#7a8a90" };

const EMPTY: FC = { type: "FeatureCollection", features: [] };

// The MapLibre worker is self-hosted from /public (copied from node_modules at the pinned version)
// so the UI never fetches code from a CDN and works fully offline.
if (typeof window !== "undefined") {
  try {
    maplibregl.setWorkerUrl(`${window.location.origin}/maplibre-gl-worker.mjs`);
  } catch {
    /* ignore — falls back to the bundler-resolved URL */
  }
}

export function SectorMap({ overlay, height = 420, showUae = false, className = "" }: { overlay?: Overlay; height?: number; showUae?: boolean; className?: string }) {
  const { t, locale } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [base, setBase] = useState<Basemap | null>(null);
  const [uae, setUae] = useState<FC | null>(null);
  const [ready, setReady] = useState(false);
  const [layers, setLayers] = useState({ catchments: true, candidates: true, roads: true, assets: true, sensors: true });

  useEffect(() => {
    api<Basemap>("/api/geo/basemap").then(setBase).catch(() => setBase(null));
    api<FC>("/api/geo/uae").then(setUae).catch(() => setUae(null));
  }, []);

  useEffect(() => {
    if (!ref.current || mapRef.current || !base) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": "#e9f0f2" } }],
      },
      center: showUae ? [54.5, 24.4] : base.center,
      zoom: showUae ? 5.6 : base.zoom,
      attributionControl: false,
      dragRotate: false,
    });
    map.on("error", (e) => {
      // Surface style/runtime problems in the console; the UI must never fail silently.
      console.error("[SectorMap]", e.error ?? e);
      (window as unknown as { __rrMapErrors?: string[] }).__rrMapErrors = [...((window as unknown as { __rrMapErrors?: string[] }).__rrMapErrors ?? []), String(e.error?.message ?? e.error ?? e)];
    });
    map.addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: base.attribution }), "bottom-right");
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      map.addSource("sector", { type: "geojson", data: base.sector });
      map.addLayer({ id: "sector-fill", type: "fill", source: "sector", paint: { "fill-color": "#ffffff", "fill-opacity": 0.85 } });
      map.addLayer({ id: "sector-line", type: "line", source: "sector", paint: { "line-color": "#0b2a34", "line-width": 1.2, "line-dasharray": [3, 2] } });
      map.addSource("catchments", { type: "geojson", data: base.catchments });
      map.addLayer({ id: "catchments-fill", type: "fill", source: "catchments", paint: { "fill-color": ["coalesce", ["get", "band_color"], "#139aa8"], "fill-opacity": 0.18 } });
      map.addLayer({ id: "catchments-line", type: "line", source: "catchments", paint: { "line-color": ["coalesce", ["get", "band_color"], "#0c7c8a"], "line-width": 1.5 } });
      map.addSource("candidates", { type: "geojson", data: base.scene_candidates });
      map.addLayer({ id: "candidates-fill", type: "fill", source: "candidates", paint: { "fill-color": "#2563eb", "fill-opacity": 0.12 } });
      map.addLayer({ id: "candidates-line", type: "line", source: "candidates", paint: { "line-color": "#2563eb", "line-width": 1, "line-dasharray": [2, 2] } });
      map.addSource("hazard", { type: "geojson", data: EMPTY });
      map.addLayer({ id: "hazard-fill", type: "fill", source: "hazard", paint: { "fill-color": "#b42318", "fill-opacity": 0.12 } });
      map.addLayer({ id: "hazard-line", type: "line", source: "hazard", paint: { "line-color": "#b42318", "line-width": 2 } });
      map.addSource("roads", { type: "geojson", data: base.roads });
      map.addLayer({
        id: "roads",
        type: "line",
        source: "roads",
        paint: {
          "line-color": ["case", ["==", ["get", "status"], "closed"], "#b42318", ["==", ["get", "status"], "flooded"], "#2563eb", ["get", "emergency_route"], "#0c7c8a", "#8da3ab"],
          "line-width": ["case", ["get", "emergency_route"], 3, 2],
          "line-dasharray": ["case", ["==", ["get", "status"], "open"], ["literal", [1, 0]], ["literal", [2, 2]]],
        },
      });
      map.addSource("route", { type: "geojson", data: EMPTY });
      map.addLayer({ id: "route", type: "line", source: "route", paint: { "line-color": "#c89b3c", "line-width": 5, "line-opacity": 0.9 } });
      map.addSource("sensors", { type: "geojson", data: base.sensors });
      map.addLayer({
        id: "sensors",
        type: "circle",
        source: "sensors",
        paint: { "circle-radius": 5, "circle-color": ["case", ["==", ["get", "health"], "ok"], "#2f9e6b", "#b42318"], "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 },
      });
      map.addSource("assets", { type: "geojson", data: base.assets });
      map.addLayer({
        id: "assets",
        type: "circle",
        source: "assets",
        paint: {
          "circle-radius": ["match", ["get", "kind"], "underpass", 9, "pump_station", 8, "substation", 8, "hospital", 8, 6],
          "circle-color": ["match", ["get", "kind"], "underpass", "#0b2a34", "pump_station", "#0c7c8a", "substation", "#6b21a8", "hospital", "#dc2626", "water_station", "#2563eb", "mobile_pump", "#c89b3c", "#64748b"],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      if (uae) {
        map.addSource("uae", { type: "geojson", data: uae });
        map.addLayer({ id: "uae-fill", type: "fill", source: "uae", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#f7eed8", "fill-opacity": 0.6 } }, "sector-fill");
        map.addLayer({ id: "uae-line", type: "line", source: "uae", filter: ["==", ["geometry-type"], "Polygon"], paint: { "line-color": "#c89b3c", "line-width": 1.2 } }, "sector-fill");
        map.addLayer({ id: "uae-points", type: "circle", source: "uae", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": ["case", ["==", ["get", "kind"], "demo_area"], 7, 4], "circle-color": ["case", ["==", ["get", "kind"], "demo_area"], "#b42318", "#0b2a34"], "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
      }
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
      for (const id of ["assets", "sensors", "roads", "catchments-fill", "candidates-fill", "uae-points"]) {
        if (!map.getLayer(id)) continue;
        map.on("mousemove", id, (e: MapLayerMouseEvent) => {
          const f = e.features?.[0];
          if (!f) return;
          map.getCanvas().style.cursor = "pointer";
          const p = f.properties as Record<string, string>;
          const name = (locale === "ar" && p.name_ar) || p.name || p.id || p.scene_id || "";
          const extra = [p.kind, p.status, p.health, p.mechanism, p.label, p.sensitive === "true" ? "sensitive (not shown publicly)" : ""].filter(Boolean).join(" · ");
          popup.setLngLat(e.lngLat).setHTML(`<div style="font:12px system-ui"><b>${esc(name)}</b><br/>${esc(extra)}</div>`).addTo(map);
        });
        map.on("mouseleave", id, () => {
          map.getCanvas().style.cursor = "";
          popup.remove();
        });
      }
      setReady(true);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, uae]);

  // overlays
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !base) return;
    const haz = overlay?.hazard;
    (map.getSource("hazard") as maplibregl.GeoJSONSource | undefined)?.setData(haz ? (haz.type === "Feature" ? { type: "FeatureCollection", features: [haz] } : haz) : EMPTY);
    (map.getSource("route") as maplibregl.GeoJSONSource | undefined)?.setData(overlay?.route ? { type: "FeatureCollection", features: [overlay.route] } : EMPTY);
    const bands = overlay?.bands ?? {};
    const cats: FC = { ...base.catchments, features: base.catchments.features.map((f) => ({ ...f, properties: { ...f.properties, band_color: BAND_COLOR[bands[(f.properties as { id: string }).id] ?? ""] ?? undefined } })) };
    (map.getSource("catchments") as maplibregl.GeoJSONSource | undefined)?.setData(cats);
    const outage = new Set(overlay?.sensorOutage ?? []);
    const sens: FC = { ...base.sensors, features: base.sensors.features.map((f) => ({ ...f, properties: { ...f.properties, health: outage.has((f.properties as { id: string }).id) ? "outage" : (f.properties as { health: string }).health } })) };
    (map.getSource("sensors") as maplibregl.GeoJSONSource | undefined)?.setData(sens);
    const closed = new Set(overlay?.closedRoads ?? []);
    const roads: FC = { ...base.roads, features: base.roads.features.map((f) => ({ ...f, properties: { ...f.properties, status: closed.has((f.properties as { id: string }).id) ? "closed" : (f.properties as { status: string }).status } })) };
    (map.getSource("roads") as maplibregl.GeoJSONSource | undefined)?.setData(roads);
  }, [overlay, ready, base]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const vis = (ids: string[], on: boolean) => ids.forEach((id) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none"));
    vis(["catchments-fill", "catchments-line"], layers.catchments);
    vis(["candidates-fill", "candidates-line"], layers.candidates);
    vis(["roads", "route"], layers.roads);
    vis(["assets"], layers.assets);
    vis(["sensors"], layers.sensors);
  }, [layers, ready]);

  const fly = (to: "sector" | "uae") => {
    const map = mapRef.current;
    if (!map || !base) return;
    if (to === "sector") map.flyTo({ center: base.center, zoom: base.zoom });
    else map.flyTo({ center: [54.5, 24.4], zoom: 5.6 });
  };

  return (
    <div className={`relative overflow-hidden rounded-xl border border-ink-100 ${className}`} style={{ height }} data-testid="sector-map">
      <div ref={ref} className="ltr-only h-full w-full" />
      {!base && <div className="absolute inset-0 flex items-center justify-center text-sm text-ink-700/70">{t("map_attribution")}</div>}
      <div className="absolute start-2 top-2 flex flex-col gap-1 rounded-lg bg-white/90 p-2 text-[11px] shadow">
        <div className="flex gap-1">
          <button type="button" className="rounded border px-1.5 py-0.5 hover:bg-ink-100/60" onClick={() => fly("sector")}>
            {t("demo_area")}
          </button>
          <button type="button" className="rounded border px-1.5 py-0.5 hover:bg-ink-100/60" onClick={() => fly("uae")} data-testid="uae-overview">
            {t("uae_overview")}
          </button>
        </div>
        <div className="label mt-1">{t("layers")}</div>
        {(Object.keys(layers) as (keyof typeof layers)[]).map((k) => (
          <label key={k} className="flex items-center gap-1">
            <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers((l) => ({ ...l, [k]: e.target.checked }))} /> {k}
          </label>
        ))}
      </div>
      <div className="absolute bottom-6 start-2 flex flex-wrap gap-1 rounded bg-white/90 px-2 py-1 text-[10px] shadow">
        <span><i className="inline-block h-2 w-2 rounded-full bg-[#0b2a34]" /> underpass</span>
        <span><i className="inline-block h-2 w-2 rounded-full bg-[#0c7c8a]" /> pump</span>
        <span><i className="inline-block h-2 w-2 rounded-full bg-[#6b21a8]" /> substation</span>
        <span><i className="inline-block h-2 w-2 rounded-full bg-[#dc2626]" /> hospital</span>
        <span><i className="inline-block h-2 w-2 rounded-full bg-[#2563eb]" /> SAR candidate (at acquisition)</span>
        <span><i className="inline-block h-2 w-2 rounded-full bg-[#c89b3c]" /> candidate route</span>
      </div>
    </div>
  );
}

function esc(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}
