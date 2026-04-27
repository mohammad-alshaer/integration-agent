import { ReactNode } from "react";

type PageHeaderProps = {
  overline: string;
  title: ReactNode;
  subtitle?: ReactNode;
};

export function PageHeader({ overline, title, subtitle }: PageHeaderProps) {
  return (
    <div className="border-b border-mist-08 py-12 md:py-16">
      <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
        {overline}
      </p>
      <h1 className="mt-4 text-4xl md:text-6xl font-normal leading-[0.87] text-white tracking-tight">
        {title}
      </h1>
      {subtitle && (
        <div className="mt-4 text-base text-ghost max-w-3xl">{subtitle}</div>
      )}
    </div>
  );
}
