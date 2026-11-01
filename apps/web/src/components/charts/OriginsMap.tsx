"use client";

import { geoEqualEarth, geoGraticule10, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import { useMemo, useState } from "react";
import land110 from "world-atlas/land-110m.json";
import type { Feature, FeatureCollection, Geometry, MultiPoint } from "geojson";
import { useWidth } from "./useWidth";

export interface MapPoint {
  id: string;
  lat: number;
  lon: number;
  label: string;
  detail?: string;
  n?: number;
  emphasis?: boolean;
}

const LAND = feature(
  land110 as never,
  (land110 as unknown as { objects: { land: never } }).objects.land,
) as unknown as FeatureCollection<Geometry> | Feature<Geometry>;

/** Sampling locations on an Equal Earth projection, framed on the points when they are clustered. */
export function OriginsMap({
  points,
  height: fixedHeight,
  title,
  onSelect,
}: {
  points: MapPoint[];
  height?: number;
  title: string;
  onSelect?: (id: string) => void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<string | null>(null);
  const valid = points.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const height = fixedHeight ?? Math.min(480, Math.round(width * 0.5));

  const { path, project, graticule } = useMemo(() => {
    const proj = geoEqualEarth();
    if (valid.length > 0) {
      const lons = valid.map((p) => p.lon);
      const lats = valid.map((p) => p.lat);
      const pad = 12;
      const span = Math.max(Math.max(...lons) - Math.min(...lons), Math.max(...lats) - Math.min(...lats));
      // A single site or a tight cluster: frame a window of at least 40 degrees around it.
      const half = Math.max(20, span / 2 + pad);
      const cx = (Math.max(...lons) + Math.min(...lons)) / 2;
      const cy = (Math.max(...lats) + Math.min(...lats)) / 2;
      const frame: MultiPoint = {
        type: "MultiPoint",
        coordinates: [
          [Math.max(-180, cx - half), Math.max(-85, cy - half * 0.6)],
          [Math.min(180, cx + half), Math.min(85, cy + half * 0.6)],
          [Math.max(-180, cx - half), Math.min(85, cy + half * 0.6)],
          [Math.min(180, cx + half), Math.max(-85, cy - half * 0.6)],
        ],
      };
      proj.fitExtent(
        [
          [8, 8],
          [width - 8, height - 8],
        ],
        span > 200 ? ({ type: "Sphere" } as never) : frame,
      );
    } else {
      proj.fitExtent(
        [
          [8, 8],
          [width - 8, height - 8],
        ],
        { type: "Sphere" } as never,
      );
    }
    const p = geoPath(proj);
    return {
      path: p,
      project: (lon: number, lat: number) => proj([lon, lat]),
      graticule: p(geoGraticule10()) ?? "",
    };
  }, [valid, width, height]);

  const maxN = Math.max(1, ...valid.map((p) => p.n ?? 1));
  const hovered = valid.find((p) => p.id === hover);

  return (
    <div ref={ref} className="relative">
      <svg width={width} height={height} role="img" aria-label={title} className="block">
        <defs>
          <clipPath id="map-clip">
            <rect width={width} height={height} />
          </clipPath>
        </defs>
        <g clipPath="url(#map-clip)">
          <path d={path({ type: "Sphere" } as never) ?? ""} fill="#ffffff" stroke="#d6d6d6" strokeWidth={0.75} />
          <path d={graticule} fill="none" stroke="#f0f0f0" strokeWidth={0.5} />
          <path d={path(LAND as never) ?? ""} fill="#ededeb" stroke="#b9b9b9" strokeWidth={0.5} />
          {valid.map((p) => {
            const xy = project(p.lon, p.lat);
            if (!xy) return null;
            const r = 2.5 + 6 * Math.sqrt((p.n ?? 1) / maxN);
            const active = hover === p.id;
            return (
              <g
                key={p.id}
                transform={`translate(${xy[0]},${xy[1]})`}
                onMouseEnter={() => setHover(p.id)}
                onMouseLeave={() => setHover(null)}
                onClick={onSelect ? () => onSelect(p.id) : undefined}
                style={{ cursor: onSelect ? "pointer" : "default" }}
              >
                <circle r={Math.max(r, 9)} fill="transparent" />
                <circle
                  r={r}
                  fill={p.emphasis ? "#000" : "rgba(44,92,148,0.18)"}
                  stroke={p.emphasis ? "#fff" : "#2c5c94"}
                  strokeWidth={active ? 1.75 : 1}
                />
              </g>
            );
          })}
        </g>
      </svg>
      {hovered ? (
        <div className="pointer-events-none absolute top-2 left-2 max-w-[18rem] border border-ink bg-paper px-3 py-1.5 text-caption">
          <span className="font-medium">{hovered.label}</span>
          {hovered.detail ? <span className="block text-ink-2">{hovered.detail}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
