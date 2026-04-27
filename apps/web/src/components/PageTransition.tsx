"use client";

import { usePathname } from "next/navigation";
import { ReactNode } from "react";

// Re-mounts on every route change — keyed by pathname — so a single
// CSS keyframe (page-fade-in) plays for fade + 12px translate-up on entry.
// Animation duration ~480ms with premium cubic-bezier easing. Skipped under
// prefers-reduced-motion (handled in globals.css).
export function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div key={pathname} className="page-transition flex-1 flex flex-col">
      {children}
    </div>
  );
}
