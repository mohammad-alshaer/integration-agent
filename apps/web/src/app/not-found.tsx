import Link from "next/link";
import { Brand } from "@/components/Brand";
import { Container } from "@/components/Container";

export default function NotFound() {
  return (
    <>
      <Brand />
      <main className="flex-1">
        <Container>
          <div className="py-24 text-center">
            <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
              404
            </p>
            <h1 className="mt-4 text-4xl md:text-6xl font-normal leading-[0.87] text-white">
              not found
            </h1>
            <p className="mt-6 text-base text-ghost">
              that route or run_id does not exist.
            </p>
            <Link
              href="/"
              className="mt-8 inline-block font-mono text-[14px] text-cyan hover:underline"
            >
              ← home
            </Link>
          </div>
        </Container>
      </main>
    </>
  );
}
