"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, getHealth } from "@/lib/api";

type State = "loading" | "ok" | "down";

const POLL_INTERVAL_MS = 30_000;

export function HealthPill() {
  const [state, setState] = useState<State>("loading");
  const [provider, setProvider] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const data = await getHealth();
        if (cancelled) return;
        setState("ok");
        setProvider(data.llm_provider);
      } catch (e) {
        if (cancelled) return;
        setState("down");
        if (e instanceof ApiError) setProvider(`api ${e.status}`);
        else setProvider("offline");
      }
    }
    void check();
    const id = window.setInterval(check, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const dotColor =
    state === "ok"
      ? "bg-cyan"
      : state === "down"
        ? "bg-red-500"
        : "bg-mist-12";

  return (
    <Link
      href="/health"
      className="inline-flex items-center gap-2 rounded-pill border border-mist-10 px-3 py-1 transition-colors hover:border-mist-12"
      title={state === "ok" ? "click for /health" : "api unreachable"}
    >
      <span className="relative inline-flex h-2 w-2">
        {state === "ok" && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan opacity-60" />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${dotColor}`} />
      </span>
      <span className="font-mono text-[11px] uppercase tracking-[0.55px] text-ghost">
        {state === "loading" ? "checking…" : provider}
      </span>
    </Link>
  );
}
