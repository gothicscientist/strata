/** The Strata mark: five sediment layers in a core, youngest on top. */
export function StrataMark({ size = 22, className }: { size?: number; className?: string }) {
  const bands = ["#e9ddb4", "#cdae66", "#a46a3a", "#5f7f6e", "#34404f"];
  const h = size;
  const w = Math.round(size * 0.78);
  const step = h / bands.length;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden className={`strata-mark overflow-visible ${className ?? ""}`}>
      <defs>
        <clipPath id="strata-mark-clip">
          <rect x={0} y={0} width={w} height={h} rx={2.5} />
        </clipPath>
      </defs>
      <g>
        {bands.map((c, i) => {
          const y = i * step;
          const wobble = i % 2 ? 1.1 : -1.1;
          return (
            <path
              key={c}
              d={`M0 ${y + (i ? wobble : 0)} Q ${w / 2} ${y - (i ? wobble : 0)} ${w} ${y + (i ? wobble * 0.4 : 0)} V ${h} H 0 Z`}
              fill={c}
            />
          );
        })}
      </g>
    </svg>
  );
}
