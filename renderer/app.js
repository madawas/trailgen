(() => {
  const cfg = window.__CONFIG__ || {};
  const mapContainer = document.getElementById("map");

  function fail(error) {
    window.__ERROR__ = error?.message || String(error || "Renderer failed to initialize.");
    window.__READY__ = "error";
  }

  let map;
  try {
    const style = buildStyle(cfg);

    if (!window.maplibregl) {
      fail("MapLibre failed to load (maplibregl is undefined).");
      return;
    }

    map = new maplibregl.Map({
      container: mapContainer,
      style,
      center: cfg.initialCenter || [0, 0],
      zoom: cfg.initialZoom || 3,
      pitch: cfg.pitch ?? 60,
      bearing: 0,
      antialias: true,
      attributionControl: false,
    });

    map.addControl(new maplibregl.AttributionControl({ compact: false }), "bottom-right");
  } catch (error) {
    fail(error);
    return;
  }

  map.on("load", () => {
    try {
      if (cfg.terrainTiles) {
        map.addSource("terrain-dem", {
          type: "raster-dem",
          tiles: [cfg.terrainTiles],
          tileSize: 256,
          encoding: "terrarium",
          attribution: cfg.terrainAttribution || "",
        });

        if (typeof map.setTerrain === "function") {
          map.setTerrain({ source: "terrain-dem", exaggeration: 1.2 });

          map.addLayer({
            id: "sky",
            type: "sky",
            paint: {
              "sky-type": "atmosphere",
              "sky-atmosphere-color": "#7aa2ff",
              "sky-atmosphere-halo-color": "#eef2ff",
            },
          });
        }
      }

      if (typeof map.setFog === "function") {
        map.setFog({
          range: [0.5, 10],
          color: "#dbeafe",
          "horizon-blend": 0.1,
        });
      }

      window.__READY__ = true;
    } catch (error) {
      fail(error);
    }
  });

  map.on("error", (event) => {
    const message = event?.error?.message || "";
    if (/webgl/i.test(message)) {
      fail(message);
    }
  });

  function buildStyle(cfg) {
    if (cfg.blankStyle) {
      return {
        version: 8,
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: {
              "background-color": "#0b1120",
            },
          },
        ],
      };
    }

    if (cfg.styleUrl) {
      return cfg.styleUrl;
    }

    const tiles = cfg.rasterTiles || "https://tile.openmaps.fr/opentopomap/{z}/{x}/{y}.png";
    const attribution = cfg.rasterAttribution || "";

    return {
      version: 8,
      sources: {
        "raster-tiles": {
          type: "raster",
          tiles: [tiles],
          tileSize: 256,
          attribution,
        },
      },
      layers: [
        {
          id: "base",
          type: "raster",
          source: "raster-tiles",
          paint: {
            "raster-opacity": 1.0,
          },
        },
      ],
    };
  }

  function addRouteLayer(geojson) {
    if (map.getSource("route")) {
      map.getSource("route").setData(geojson);
      return;
    }

    map.addSource("route", {
      type: "geojson",
      data: geojson,
      lineMetrics: true,
    });

    if (cfg.showOutline) {
      map.addLayer({
        id: "route-outline",
        type: "line",
        source: "route",
        paint: {
          "line-color": cfg.outlineColor || "#0f172a",
          "line-width": cfg.outlineWidth ?? 7,
          "line-opacity": 0.8,
        },
      });
    }

    map.addLayer({
      id: "route-line",
      type: "line",
      source: "route",
      paint: {
        "line-gradient": [
          "case",
          ["<", ["line-progress"], 0],
          cfg.routeColor || "#3b82f6",
          "rgba(0,0,0,0)",
        ],
        "line-width": cfg.routeWidth ?? 4,
      },
    });
  }

  function addMarkers(geojson) {
    if (map.getSource("markers")) {
      map.getSource("markers").setData(geojson);
      return;
    }

    if (!cfg.showMarkers) {
      return;
    }

    map.addSource("markers", {
      type: "geojson",
      data: geojson,
    });

    map.addLayer({
      id: "markers",
      type: "circle",
      source: "markers",
      paint: {
        "circle-radius": 6,
        "circle-color": ["get", "color"],
        "circle-stroke-width": 2,
        "circle-stroke-color": "#0f172a",
      },
    });
  }

  window.__setRoute = (geojson) => {
    addRouteLayer(geojson);
    window.__ROUTE_READY__ = true;
  };

  window.__setMarkers = (geojson) => {
    addMarkers(geojson);
  };

  window.__renderFrame = (camera) => {
    return new Promise((resolve) => {
      map.once("idle", () => resolve(true));
      map.jumpTo({
        center: camera.center,
        zoom: camera.zoom,
        bearing: camera.bearing,
        pitch: camera.pitch,
      });
      if (typeof camera.progress === "number") {
        const progress = Math.min(1, Math.max(0, camera.progress));
        const gradient = [
          "case",
          ["<=", ["line-progress"], progress],
          cfg.routeColor || "#3b82f6",
          "rgba(0,0,0,0)",
        ];
        if (map.getLayer("route-line")) {
          map.setPaintProperty("route-line", "line-gradient", gradient);
        }
      }
    });
  };
})();
