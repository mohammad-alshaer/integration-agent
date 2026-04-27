type SelectProps = {
  label: string;
  value: string;
  onChange: (next: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
  disabled?: boolean;
};

export function Select({
  label,
  value,
  onChange,
  options,
  placeholder = "—",
  disabled = false,
}: SelectProps) {
  return (
    <div>
      <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
        {label}
      </p>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={`mt-2 w-full appearance-none rounded-md border px-4 py-3 font-mono text-[14px] tracking-[-0.28px] transition-colors ${
          disabled
            ? "border-mist-04 bg-black/50 text-phantom cursor-not-allowed"
            : "border-mist-10 bg-black text-white hover:border-mist-12 focus:border-signal focus:outline-none"
        }`}
      >
        <option value="" disabled className="bg-void text-whisper">
          {placeholder}
        </option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value} className="bg-void text-white">
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
