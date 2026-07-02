from processing.chunking.cvm_parecer_chunker import *
import pandas as pd
df = pd.read_parquet("data/processed/cvm/dfp/2023/dfp_cia_aberta_parecer_2023.parquet")
col = detect_text_column(df)
print(col)                    # deve ser algo como "TX_PARECER" ou similar
print(df[col].iloc[0][:200]) # deve parecer início de relatório de auditoria
exit()