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
      maxZoom: cfg.maxZoom ?? 16,
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
          encoding: cfg.terrainEncoding || "terrarium",
          attribution: cfg.terrainAttribution || "",
        });

        if (typeof map.setTerrain === "function") {
          map.setTerrain({
            source: "terrain-dem",
            exaggeration: cfg.terrainExaggeration ?? 1.2,
          });

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


  window.__setRoute = (geojson) => {
    addRouteLayer(geojson);
    window.__ROUTE_READY__ = true;
  };


  window.__renderFrame = (camera) => {
    return new Promise((resolve) => {
      const timeoutMs = cfg.frameTimeoutMs ?? 15000;
      const waitEvent = cfg.frameWait ?? "idle";
      const delayMs = cfg.frameDelayMs ?? 0;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        resolve(true);
      };
      const finishWithDelay = () => {
        if (delayMs > 0) {
          window.setTimeout(finish, delayMs);
        } else {
          finish();
        }
      };
      const timeout = window.setTimeout(finish, timeoutMs);
      map.once(waitEvent, () => {
        window.clearTimeout(timeout);
        finishWithDelay();
      });
      if (camera && camera.free && camera.position && typeof map.setFreeCameraOptions === "function") {
        const opts = map.getFreeCameraOptions();
        const altitude = camera.altitude ?? 0;
        opts.position = maplibregl.MercatorCoordinate.fromLngLat(camera.position, altitude);
        if (camera.target && typeof opts.lookAtPoint === "function") {
          opts.lookAtPoint(camera.target);
        } else if (typeof opts.setPitchBearing === "function") {
          if (typeof camera.pitch === "number" && typeof camera.bearing === "number") {
            opts.setPitchBearing(camera.pitch, camera.bearing);
          }
        }
        map.setFreeCameraOptions(opts);
      } else if (camera && camera.position && camera.target && typeof map.calculateCameraOptionsFromTo === "function") {
        const from = new maplibregl.LngLat(camera.position[0], camera.position[1]);
        const to = new maplibregl.LngLat(camera.target[0], camera.target[1]);
        const opts = map.calculateCameraOptionsFromTo(
          from,
          camera.altitude ?? 0,
          to,
          0
        );
        map.jumpTo({
          center: opts.center,
          zoom: opts.zoom,
          bearing: opts.bearing,
          pitch: opts.pitch,
        });
      } else {
        map.jumpTo({
          center: camera.center,
          zoom: camera.zoom,
          bearing: camera.bearing,
          pitch: camera.pitch,
        });
      }
      map.triggerRepaint();
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
