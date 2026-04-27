"use client";

import { useRef, useState } from "react";
import { SchemaProfile } from "@/lib/api";

type ProfileUploaderProps = {
  label: string;
  hint: string;
  onLoad: (profile: SchemaProfile | null) => void;
};

function isSchemaProfile(value: unknown): value is SchemaProfile {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.database_name === "string" &&
    Array.isArray(v.tables) &&
    v.tables.every(
      (t) =>
        t &&
        typeof t === "object" &&
        typeof (t as Record<string, unknown>).table_schema === "string" &&
        typeof (t as Record<string, unknown>).table_name === "string",
    )
  );
}

export function ProfileUploader({ label, hint, onLoad }: ProfileUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [bytes, setBytes] = useState<number>(0);
  const [tables, setTables] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setError(null);
    setFilename(file.name);
    setBytes(file.size);
    try {
      const text = await file.text();
      const json = JSON.parse(text);
      if (!isSchemaProfile(json)) {
        throw new Error(
          "not a SchemaProfile: expected { database_name, tables: [{ table_schema, table_name, ... }], ... }",
        );
      }
      setTables(json.tables.length);
      onLoad(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to parse file");
      onLoad(null);
    }
  }

  function clear() {
    setFilename(null);
    setBytes(0);
    setTables(0);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
    onLoad(null);
  }

  return (
    <div>
      <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
        {label}
      </p>
      <label
        className={`mt-2 flex cursor-pointer items-center justify-between gap-4 rounded-md border px-4 py-3 transition-colors ${
          error
            ? "border-red-500/40 bg-red-500/5"
            : filename
              ? "border-cyan/40 bg-[var(--color-cyan-glow)]"
              : "border-mist-10 bg-black hover:border-mist-12"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/json,.json"
          className="sr-only"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleFile(f);
          }}
        />
        <div className="min-w-0 flex-1">
          {filename ? (
            <>
              <div className="truncate font-mono text-[14px] tracking-[-0.28px] text-white">
                {filename}
              </div>
              <div className="font-mono text-[12px] text-whisper">
                {(bytes / 1024 / 1024).toFixed(2)} MB · {tables} tables
              </div>
            </>
          ) : (
            <>
              <div className="text-base text-ghost">{hint}</div>
              <div className="font-mono text-[12px] text-whisper">
                click to choose a .json file
              </div>
            </>
          )}
        </div>
        {filename && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              clear();
            }}
            className="font-mono text-[12px] uppercase tracking-[0.55px] text-whisper hover:text-cyan transition-colors"
          >
            clear
          </button>
        )}
      </label>
      {error && (
        <p className="mt-2 font-mono text-[12px] text-red-400">{error}</p>
      )}
    </div>
  );
}
