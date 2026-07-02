"""
Definição das ferramentas disponíveis para o assessor, no formato exato
que a API da Anthropic espera no parâmetro `tools` de uma chamada.

Cada ferramenta tem:
  name        — identificador, o mesmo que o LLM vai colocar em tool_use blocks
  description — instrução em linguagem natural de QUANDO usar essa ferramenta
  input_schema — JSON Schema do input que o LLM vai gerar

A `description` é crítica: é o que o Claude lê pra decidir se deve ou não
chamar a ferramenta. Vale ajustar o texto conforme os testes de uso real.
"""
from __future__ import annotations

GET_MARKET_QUOTE: dict = {
    "name": "get_market_quote",
    "description": (
        "Busca a cotação atual de uma ou mais ações da B3 (bolsa de valores brasileira) "
        "em tempo real via brapi.dev. Use esta ferramenta quando o usuário perguntar sobre "
        "preço atual, variação do dia, máximas/mínimas ou qualquer dado de mercado em tempo "
        "real de ações específicas. NÃO use para dados históricos de demonstrações financeiras "
        "(esses já estão na base de conhecimento)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tickers": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Lista de tickers de ações da B3. Exemplos: ['ITUB4'], "
                    "['BBSE3', 'ITUB4'], ['PETR4', 'VALE3']. "
                    "Sempre use letras maiúsculas e inclua o sufixo numérico (3, 4, 11...)."
                ),
            }
        },
        "required": ["tickers"],
    },
}

# Lista completa de ferramentas disponíveis — passada pra API em cada chamada.
ALL_TOOLS: list[dict] = [GET_MARKET_QUOTE]
