import Link from "next/link";
import { Container } from "./Container";

export function Brand() {
  return (
    <header className="border-b border-mist-06">
      <Container>
        <div className="flex items-center justify-between py-6">
          <Link href="/" className="flex items-center gap-3 group">
            <span className="font-mono text-[11px] uppercase tracking-[0.55px] text-whisper">
              M2 · 78.9% / 96.7%
            </span>
            <span className="block w-px h-4 bg-mist-12" aria-hidden />
            <span className="font-mono text-base text-white tracking-[-0.32px] group-hover:text-cyan transition-colors">
              integration-agent
            </span>
          </Link>
          <nav className="flex gap-8 text-base">
            <Link href="/eval" className="text-ghost hover:text-white transition-colors">
              evaluations
            </Link>
            <Link href="/map" className="text-ghost hover:text-white transition-colors">
              map
            </Link>
          </nav>
        </div>
      </Container>
    </header>
  );
}
