"use client";

import { useState, type KeyboardEvent } from "react";

type Props = {
  onSend: (text: string) => void;
  disabled?: boolean;
};

export function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");

  function handleSubmit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className="flex items-end gap-3 rounded-lg border border-hairline bg-bg-elevated p-3">
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={1}
        placeholder="Pergunte sobre uma demonstração financeira..."
        className="flex-1 resize-none bg-transparent text-ink placeholder:text-ink-faint focus:outline-none"
      />
      <button
        onClick={handleSubmit}
        disabled={disabled || !value.trim()}
        className="rounded bg-gold px-4 py-2 font-mono text-sm font-medium text-bg transition-colors hover:bg-gold-hover disabled:cursor-not-allowed disabled:opacity-40"
      >
        Enviar
      </button>
    </div>
  );
}
