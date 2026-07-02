import type { Source } from "@/types/chat";

const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

function formatPeriod(period: string | null): string {
  if (!period) return "—";
  const parts = period.split("-");
  if (parts.length !== 3) return period;
  const [year, month] = parts;
  const idx = parseInt(month, 10) - 1;
  return `${MONTHS[idx] ?? month}/${year}`;
}

export function SourceChip({ source }: { source: Source }) {
  const relevancePct = Math.round(source.score * 100);

  return (
    <div className="flex items-center gap-3 rounded border border-hairline bg-bg-elevated px-3 py-2 text-xs">
      <span className="tabular font-mono text-gold">{relevancePct}%</span>
      <div className="flex flex-col">
        <span className="font-body text-ink">{source.company_name ?? "Empresa desconhecida"}</span>
        <span className="font-mono text-ink-muted">
          {source.statement_type ?? "—"} · {formatPeriod(source.period_end)}
        </span>
      </div>
    </div>
  );
}
