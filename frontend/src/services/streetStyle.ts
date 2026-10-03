import type { ExpressionSpecification, StyleSpecification } from "maplibre-gl";
import latinFont from "../assets/maps/NotoSans-Regular.ttf?url";
import arabicFont from "../assets/maps/NotoSansArabic-Regular.ttf?url";

/** Cartographic display only. Geometry and names come from OSM/OpenMapTiles;
 * this style never invents streets or affects simulation state. Font and style
 * are bundled locally; vector geography still requires OpenFreeMap access. */
export const streetAttribution =
  '<a href="https://openfreemap.org/">OpenFreeMap</a> · <a href="https://openmaptiles.org/">© OpenMapTiles</a> · <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a>';

const name: ExpressionSpecification = [
  "coalesce",
  ["get", "name:en"],
  ["get", "name:latin"],
  ["get", "name"],
];

export function createStreetStyle(): StyleSpecification {
  const road = { source: "streets", "source-layer": "transportation" };
  return {
    version: 8,
    name: "AutoNOC Midnight Streets",
    "font-faces": {
      "NOC Map": [
        { url: new URL(latinFont, window.location.href).href },
        { url: new URL(arabicFont, window.location.href).href },
      ],
    },
    sources: {
      streets: {
        type: "vector",
        url: "https://tiles.openfreemap.org/planet",
        attribution: streetAttribution,
      },
    },
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": "#061426" },
      },
      {
        id: "landuse",
        type: "fill",
        source: "streets",
        "source-layer": "landuse",
        paint: { "fill-color": "#0b1b2a", "fill-opacity": 0.35 },
      },
      {
        id: "parks",
        type: "fill",
        source: "streets",
        "source-layer": "park",
        paint: { "fill-color": "#10272b", "fill-opacity": 0.45 },
      },
      {
        id: "water",
        type: "fill",
        source: "streets",
        "source-layer": "water",
        paint: { "fill-color": "#03101e" },
      },
      {
        id: "waterways",
        type: "line",
        source: "streets",
        "source-layer": "waterway",
        paint: { "line-color": "#153448", "line-width": 1 },
      },
      {
        id: "buildings",
        type: "fill",
        minzoom: 13,
        source: "streets",
        "source-layer": "building",
        paint: {
          "fill-color": "#213044",
          "fill-opacity": 0.5,
          "fill-outline-color": "#28394b",
        },
      },
      {
        id: "road-minor",
        type: "line",
        ...road,
        filter: [
          "!",
          [
            "in",
            ["get", "class"],
            ["literal", ["motorway", "trunk", "primary", "secondary"]],
          ],
        ],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#6c7c8d",
          "line-opacity": 0.5,
          "line-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            10,
            0.35,
            13,
            0.75,
            16,
            2.1,
            19,
            5,
          ],
        },
      },
      {
        id: "road-major-casing",
        type: "line",
        ...road,
        filter: [
          "in",
          ["get", "class"],
          ["literal", ["motorway", "trunk", "primary", "secondary"]],
        ],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#0b1728",
          "line-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            10,
            2,
            14,
            4.5,
            18,
            10,
          ],
        },
      },
      {
        id: "road-major",
        type: "line",
        ...road,
        filter: [
          "in",
          ["get", "class"],
          ["literal", ["motorway", "trunk", "primary", "secondary"]],
        ],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#a5b1bb",
          "line-opacity": 0.7,
          "line-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            10,
            0.65,
            13,
            1.15,
            16,
            2.8,
            19,
            7,
          ],
        },
      },
      {
        id: "airport",
        type: "line",
        source: "streets",
        "source-layer": "aeroway",
        paint: {
          "line-color": "#46576c",
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1, 15, 6],
        },
      },
      {
        id: "street-names",
        type: "symbol",
        minzoom: 11,
        source: "streets",
        "source-layer": "transportation_name",
        layout: {
          "symbol-placement": "line",
          "text-field": name,
          "text-font": ["NOC Map"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 11, 10, 16, 12],
          "symbol-spacing": 250,
          "text-max-angle": 35,
          "text-padding": 3,
        },
        paint: {
          "text-color": "#aebbc9",
          "text-halo-color": "#061426",
          "text-halo-width": 1.7,
          "text-opacity": 0.9,
        },
      },
      {
        id: "place-names",
        type: "symbol",
        minzoom: 10,
        source: "streets",
        "source-layer": "place",
        filter: [
          "in",
          ["get", "class"],
          ["literal", ["city", "town", "village", "suburb", "neighbourhood"]],
        ],
        layout: {
          "text-field": name,
          "text-font": ["NOC Map"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 10, 10, 15, 12],
          "text-max-width": 10,
          "text-padding": 20,
        },
        paint: {
          "text-color": "#8196ad",
          "text-halo-color": "#061426",
          "text-halo-width": 2,
        },
      },
      {
        id: "poi-names",
        type: "symbol",
        minzoom: 15,
        source: "streets",
        "source-layer": "poi",
        filter: [
          "in",
          ["get", "class"],
          ["literal", ["hospital", "school", "university", "park"]],
        ],
        layout: {
          "text-field": name,
          "text-font": ["NOC Map"],
          "text-size": 10,
          "text-max-width": 12,
          "text-padding": 12,
        },
        paint: {
          "text-color": "#7d959f",
          "text-halo-color": "#061426",
          "text-halo-width": 1.5,
        },
      },
    ],
  };
}
