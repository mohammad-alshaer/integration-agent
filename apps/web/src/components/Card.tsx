import { ReactNode } from "react";

type CardProps = {
  children: ReactNode;
  className?: string;
  brutalist?: boolean;
};

export function Card({ children, className = "", brutalist = false }: CardProps) {
  const shadow = brutalist ? "shadow-[var(--shadow-brutalist)]" : "";
  return (
    <div
      className={`rounded-md border border-mist-10 bg-black p-6 ${shadow} ${className}`}
    >
      {children}
    </div>
  );
}
