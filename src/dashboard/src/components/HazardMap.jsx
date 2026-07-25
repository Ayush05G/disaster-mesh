import { useEffect, useRef } from "react";
// maplibre-gl v6 dropped the default export — named imports only.
import { Map as MaplibreMap, NavigationControl, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// Fully inline style: background + graticule + hazard layers. Deliberately
// no text layers (text needs glyph PBFs — a network fetch), no sprite, no
// tile sources. Zero external requests by construction (Critical Rule 1).
// A local PMTiles basemap is the recorded upgrade path once a demo region
// is chosen (the extract is a sized download needing an explicit OK — see
// ROADMAP Phase 4 status); everything here keeps working when it lands.

const SEVERITY_COLORS = {
  LOW: "#4a9eff",
  MEDIUM: "#ffb020",
  HIGH: "#ff4d4d",
};

function buildGraticule() {
  const features = [];
  for (let lng = -180; lng <= 180; lng += 15) {
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[lng, -85], [lng, 85]] },
    });
  }
  for (let lat = -75; lat <= 75; lat += 15) {
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[-180, lat], [180, lat]] },
    });
  }
  return { type: "FeatureCollection", features };
}

function hazardsToGeoJSON(hazards) {
  return {
    type: "FeatureCollection",
    features: hazards.map((envelope) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [envelope.payload.coordinates.lng, envelope.payload.coordinates.lat],
      },
      properties: {
        event_id: envelope.event_id,
        node_id: envelope.node_id,
        hazard_type: envelope.payload.hazard_type,
        severity: envelope.payload.severity,
        timestamp: envelope.payload.timestamp,
      },
    })),
  };
}

const INLINE_STYLE = {
  version: 8,
  sources: {
    graticule: { type: "geojson", data: buildGraticule() },
    hazards: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#101418" } },
    {
      id: "graticule",
      type: "line",
      source: "graticule",
      paint: { "line-color": "#1e2830", "line-width": 1 },
    },
    {
      id: "hazard-glow",
      type: "circle",
      source: "hazards",
      paint: {
        "circle-radius": 14,
        "circle-color": [
          "match", ["get", "severity"],
          "HIGH", SEVERITY_COLORS.HIGH,
          "MEDIUM", SEVERITY_COLORS.MEDIUM,
          SEVERITY_COLORS.LOW,
        ],
        "circle-opacity": 0.25,
      },
    },
    {
      id: "hazard-dot",
      type: "circle",
      source: "hazards",
      paint: {
        "circle-radius": 5,
        "circle-color": [
          "match", ["get", "severity"],
          "HIGH", SEVERITY_COLORS.HIGH,
          "MEDIUM", SEVERITY_COLORS.MEDIUM,
          SEVERITY_COLORS.LOW,
        ],
        "circle-stroke-width": 1.5,
        "circle-stroke-color": "#ffffff",
      },
    },
  ],
};

export function HazardMap({ hazards }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const loadedRef = useRef(false);

  useEffect(() => {
    const map = new MaplibreMap({
      container: containerRef.current,
      style: INLINE_STYLE,
      center: [0, 20],
      zoom: 1.3,
      attributionControl: false,
    });
    map.addControl(new NavigationControl({ showCompass: false }));

    map.on("load", () => {
      loadedRef.current = true;
    });

    map.on("click", "hazard-dot", (e) => {
      const props = e.features[0].properties;
      new Popup({ closeButton: true })
        .setLngLat(e.lngLat)
        .setHTML(
          `<div class="popup">` +
            `<strong>${props.hazard_type}</strong> ` +
            `<span class="sev sev-${props.severity}">${props.severity}</span><br/>` +
            `${props.event_id}<br/>` +
            `<small>${props.timestamp}</small>` +
            `</div>`,
        )
        .addTo(map);
    });
    map.on("mouseenter", "hazard-dot", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "hazard-dot", () => {
      map.getCanvas().style.cursor = "";
    });

    mapRef.current = map;
    return () => {
      loadedRef.current = false;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    const apply = () => map.getSource("hazards").setData(hazardsToGeoJSON(hazards));
    if (loadedRef.current) {
      apply();
    } else {
      map.once("load", apply);
    }
  }, [hazards]);

  return <div ref={containerRef} className="map-container" />;
}
