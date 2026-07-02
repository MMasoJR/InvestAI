const EXAMPLES = [
  "Qual o ativo total da empresa no último balanço disponível?",
  "Como evoluiu o patrimônio líquido entre os períodos disponíveis?",
  "Quais as principais contas do passivo circulante?",
];

type Props = {
  onExampleClick: (text: string) => void;
};

export function EmptyState({ onExampleClick }: Props) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
      <div>
        <h1 className="font-display text-3xl text-ink">InvestAI</h1>
        <p className="mt-2 font-mono text-xs uppercase tracking-widest text-ink-muted">
          Assessor baseado em demonstrações financeiras da CVM
        </p>
      </div>
      <div className="flex flex-col gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            onClick={() => onExampleClick(example)}
            className="rounded border border-hairline px-4 py-2 text-left text-sm text-ink-muted transition-colors hover:border-gold/50 hover:text-ink"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}
