export function Logo({ size = 'default' }) {
  const isSmall = size === 'sm'

  const width = isSmall ? 90 : 140
  const height = isSmall ? 20 : 28
  const stroke = isSmall ? 2 : 2.5

  return (
    <div
      className={`logo ${isSmall ? 'logo--sm' : ''}`}
      role="img"
      aria-label="SwipeHome"
    >
      <span className={`logo__text${isSmall ? ' logo__text--sm' : ''}`}>
        SwipeHome
      </span>

      <div className="logo__rooflines" aria-hidden="true">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <polyline
            points={
              `1,${height - 2} ` +
              `${width * 0.25},2 ` +
              `${width * 0.5},${height - 2} ` +
              `${width * 0.75},2 ` +
              `${width - 1},${height - 2}`
            }
            stroke="#E8001C"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </div>
  )
}