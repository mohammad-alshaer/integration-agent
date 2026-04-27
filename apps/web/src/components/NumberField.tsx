type NumberFieldProps = {
  label: string;
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
};

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  hint,
}: NumberFieldProps) {
  return (
    <div>
      <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
        {label}
      </p>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isNaN(n)) onChange(n);
        }}
        className="mt-2 w-full rounded-md border border-mist-10 bg-black px-4 py-3 font-mono text-[14px] tracking-[-0.28px] text-white hover:border-mist-12 focus:border-signal focus:outline-none"
      />
      {hint && (
        <p className="mt-1 font-mono text-[12px] text-whisper">{hint}</p>
      )}
    </div>
  );
}

type ToggleProps = {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  hint?: string;
};

export function Toggle({ label, checked, onChange, hint }: ToggleProps) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-md border border-mist-10 bg-black px-4 py-3 hover:border-mist-12 transition-colors">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-4 w-4 cursor-pointer accent-cyan"
      />
      <div className="flex-1">
        <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-white">
          {label}
        </p>
        {hint && (
          <p className="mt-1 font-mono text-[12px] text-whisper">{hint}</p>
        )}
      </div>
    </label>
  );
}
