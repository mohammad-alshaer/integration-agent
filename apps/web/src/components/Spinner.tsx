export function Spinner({ size = 24 }: { size?: number }) {
  return (
    <span
      className="inline-block animate-spin rounded-full border-2 border-cyan/20 border-t-cyan"
      style={{ width: size, height: size }}
      aria-label="loading"
    />
  );
}

export function PulseDot() {
  return (
    <span className="relative inline-flex h-2 w-2">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan opacity-75" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan" />
    </span>
  );
}
