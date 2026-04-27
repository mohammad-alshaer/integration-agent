import Link from "next/link";
import { Container } from "@/components/Container";

export default function NotFound() {
  return (
    <main className="flex-1 relative">
      <Container>
        <div className="py-24 text-center stagger stagger-1">
          <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
            404
          </p>
          <h1 className="mt-4 text-5xl md:text-7xl font-normal leading-[0.87] tracking-[-0.04em]">
            <span className="text-gradient-cyan">not found</span>
          </h1>
          <p className="mt-6 text-base text-ghost">
            that route or run_id does not exist.
          </p>
          <Link
            href="/"
            className="mt-8 inline-flex items-center gap-2 font-mono text-[14px] text-cyan hover:text-white transition-colors"
          >
            <span aria-hidden>←</span> home
          </Link>
        </div>
      </Container>
    </main>
  );
}
