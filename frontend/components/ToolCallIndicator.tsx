"use client";

const TOOL_LABELS: Record<string, string> = {
  get_market_quote: "Buscando cotação em tempo real",
};

type Props = {
  name: string;
  input: Record<string, unknown>;
  result?: string;
};

export function ToolCallIndicator({ name, input, result }: Props) {
  const label = TOOL_LABELS[name] ?? name;
  const tickers = Array.isArray(input?.tickers)
    ? (input.tickers as string[]).join(", ")
    : "";

  return (
    <div className="my-2 rounded border border-hairline bg-bg-elevated px-3 py-2 text-xs">
      <div className="flex items-center gap-2">
        {/* Indicador de status: animado se sem resultado, estático se concluído */}
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            result ? "bg-positive" : "animate-pulse bg-gold"
          }`}
        />
        <span className="font-mono text-ink-muted">
          {label}
          {tickers && (
            <span className="ml-1 text-gold">{tickers}</span>
          )}
        </span>
      </div>
      {result && (
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-ink-muted">
          {result}
        </pre>
      )}
    </div>
  );
}
