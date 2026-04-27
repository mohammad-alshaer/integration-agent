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
  const [dragOver, setDragOver] = useState(false);

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

  function onDragEnter(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer?.types?.includes("Files")) setDragOver(true);
  }
  function onDragOver(e: React.DragEvent<HTMLLabelElement>) {
    // Required so onDrop fires.
    e.preventDefault();
    e.stopPropagation();
    if (!dragOver && e.dataTransfer?.types?.includes("Files")) setDragOver(true);
  }
  function onDragLeave(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    // Only clear if leaving the label entirely (not just moving over a child).
    const related = e.relatedTarget as Node | null;
    if (!related || !e.currentTarget.contains(related)) setDragOver(false);
  }
  function onDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) void handleFile(f);
  }

  const stateClass = error
    ? "border-red-500/40 bg-red-500/5"
    : dragOver
      ? "border-cyan border-dashed bg-[var(--color-cyan-glow)] shadow-[0_0_0_4px_rgba(0,255,255,0.08),0_20px_60px_-20px_rgba(0,255,255,0.35)]"
      : filename
        ? "border-cyan/40 bg-[var(--color-cyan-glow)]"
        : "border-mist-10 bg-black/40 hover:border-mist-12 hover:bg-black/60";

  return (
    <div>
      <p className="font-mono text-[12px] uppercase tracking-[0.7px] text-whisper">
        {label}
      </p>
      <label
        onDragEnter={onDragEnter}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`relative mt-2 flex cursor-pointer items-center justify-between gap-4 rounded-md border-2 px-4 py-4 backdrop-blur transition-all duration-200 ${stateClass}`}
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
              <div className="flex items-center gap-2">
                <CheckIcon />
                <div className="truncate font-mono text-[14px] tracking-[-0.28px] text-white">
                  {filename}
                </div>
              </div>
              <div className="mt-1 font-mono text-[12px] text-whisper">
                {(bytes / 1024 / 1024).toFixed(2)} MB · {tables} tables
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center gap-3">
                <UploadIcon active={dragOver} />
                <div className={dragOver ? "text-cyan" : "text-ghost"}>
                  {dragOver ? "drop to upload" : hint}
                </div>
              </div>
              <div className="mt-1 ml-9 font-mono text-[12px] text-whisper">
                drag a .json here or click to choose
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

function UploadIcon({ active = false }: { active?: boolean }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 transition-colors ${active ? "stroke-cyan" : "stroke-whisper"}`}
      aria-hidden
    >
      <path d="M12 16V4" />
      <path d="m6 10 6-6 6 6" />
      <path d="M4 20h16" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0 stroke-cyan"
      aria-hidden
    >
      <path d="m5 12 5 5L20 7" />
    </svg>
  );
}
