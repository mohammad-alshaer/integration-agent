// App-wide animated aurora background. Lives in layout so every route inherits
// the same atmosphere. Respects prefers-reduced-motion via globals.css.

export function AuroraShell() {
  return (
    <div className="aurora-shell" aria-hidden>
      <div className="aurora-grid" />
      <div className="aurora-blob aurora-cobalt" />
      <div className="aurora-blob aurora-cyan-top" />
      <div className="aurora-blob aurora-signal" />
      <div className="aurora-blob aurora-cyan" />
    </div>
  );
}
