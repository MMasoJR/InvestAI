"use client";

import { useState } from "react";

type Props = {
  mode: "login" | "register";
  onSubmit: (email: string, password: string) => Promise<void>;
  error?: string | null;
  loading?: boolean;
};

export function AuthForm({ mode, onSubmit, error, loading }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await onSubmit(email, password);
  }

  return (
    <div className="mx-auto mt-24 w-full max-w-sm">
      <div className="mb-8 text-center">
        <h1 className="font-display text-3xl text-ink">InvestAI</h1>
        <p className="mt-2 font-mono text-xs uppercase tracking-widest text-ink-muted">
          {mode === "login" ? "Entrar na conta" : "Criar conta"}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <label className="font-mono text-xs text-ink-muted">E-mail</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="seu@email.com"
            className="rounded border border-hairline bg-bg-elevated px-3 py-2 text-ink placeholder:text-ink-faint focus:border-gold focus:outline-none"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="font-mono text-xs text-ink-muted">Senha</label>
          <input
            type="password"
            required
            minLength={mode === "register" ? 8 : 1}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === "register" ? "Mínimo 8 caracteres" : "••••••••"}
            className="rounded border border-hairline bg-bg-elevated px-3 py-2 text-ink placeholder:text-ink-faint focus:border-gold focus:outline-none"
          />
        </div>

        {error && (
          <p className="rounded border border-negative/30 bg-negative/10 px-3 py-2 font-mono text-xs text-negative">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="rounded bg-gold py-2 font-mono text-sm font-medium text-bg transition-colors hover:bg-gold-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "Aguarde..." : mode === "login" ? "Entrar" : "Criar conta"}
        </button>
      </form>

      <p className="mt-6 text-center font-mono text-xs text-ink-muted">
        {mode === "login" ? (
          <>
            Sem conta?{" "}
            <a href="/register" className="text-gold hover:underline">
              Criar conta
            </a>
          </>
        ) : (
          <>
            Já tem conta?{" "}
            <a href="/login" className="text-gold hover:underline">
              Entrar
            </a>
          </>
        )}
      </p>
    </div>
  );
}
