const UNITS = ["B", "kB", "MB", "GB"] as const;

/** Sizes are decorative here, so one decimal place and no locale wiring is enough. */
export const formatBytes = (bytes: number): string => {
  let value = bytes;
  let unit = 0;

  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }

  return `${unit === 0 ? value : value.toFixed(1)} ${UNITS[unit]}`;
};
