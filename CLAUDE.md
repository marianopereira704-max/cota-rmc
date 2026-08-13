# Cota RMC — Contexto do projeto

Comparativo entre o preço de compra real das lojas da Rede Melhor Compra e a
tabela de preço RMC (Rede de Melhor Compra) por laboratório, com detecção de
Oportunidade (positivação) e Risco de Ruptura, e sugestão de pedido baseada
em demanda diária.

## Status desta entrega

Construído e **testado com os 3 arquivos reais** fornecidos por Mariano
(BASE_COMPLETA.xlsx, TABELA_UNIFICADA_RANBAXY.xlsx, DADOS_LOJAS__COMPRA_POR_CNPJ.xlsx):

- ✅ `config.py` — todos os parâmetros de negócio como variáveis (dias de
  cobertura, margem de segurança, nomes de coluna esperados). Nada hardcoded
  dentro da lógica.
- ✅ `modules/data_loader.py` — leitura e limpeza dos 3 tipos de arquivo,
  testado end-to-end. Remove rodapé de export do GPS Farma, linha "Total",
  registros sem CNPJ/EAN, agrega duplicidade cnpj+EAN.
- ✅ `modules/matching_engine.py` — RMC como âncora, resolução via
  BASE_COMPLETA, aliases persistidos por (ean, laboratorio_rmc). Testado:
  reproduziu exatamente os 17 EANs pendentes identificados manualmente na
  conversa (Amoxicilina+Clavulanato, Etoricoxibe, Lurasidona, Oxcarbazepina),
  e a resolução via alias levou a cobertura de 87.1% → 100%.
- ✅ `modules/business_rules.py` — tabela principal (cross join loja x
  produto RMC, incluindo lojas sem movimento = base do status Oportunidade),
  Preço Compra derivado (`Fat. líquido × %CMV / Quantidade`), classificação
  Oportunidade/Risco de Ruptura/Normal, Pedido Sugerido. Testado com dados reais.
- ✅ `modules/storage.py` — cliente Spaces isolado em prefixo `Cota RMC/`,
  não testado contra bucket real (sem credenciais nesta sessão) mas a
  interface foi validada por leitura de código e uso no app.
- ✅ `modules/auth.py` — login funcional baseado em `st.secrets`.
- ✅ `modules/styles.py` — tokens da identidade visual (skill
  `mariano-identidade-visual`) aplicados: navy/verde, badges de status sem
  vermelho (Ruptura usa âmbar), mesh gradient restrito ao cabeçalho.
- ✅ `app.py` — sobe sem erro (testado com `streamlit run`, HTTP 200, log
  limpo), 5 abas: Dados, Configurações, Tabela Principal, Pedido Sugerido,
  Dashboard.

## O que precisa de atenção / revisão antes de considerar pronto para o diretor

1. **Tela de login** — o app.py referencia "a identidade visual que já
   decidimos, inclusive a tela de login", mas eu não tive acesso ao código
   real do PEX 2.0 ou Mapa da Farmácia nesta sessão (nenhum arquivo foi
   enviado). Construí `modules/auth.py` seguindo os tokens de design
   documentados na skill, mas **não é garantidamente pixel-perfect** com a
   tela de login já usada nos outros projetos. Se houver um componente de
   login compartilhado entre projetos, ele deve substituir este.
2. **Dashboard (aba 5)** — os indicadores implementados (desvio médio de
   preço, economia potencial, ranking de lojas, ranking de produtos,
   contagem de Oportunidade/Ruptura) foram **minha sugestão original**,
   confirmada implicitamente mas não linha a linha por Mariano. Antes de
   apresentar ao diretor, validar com ele se são esses os indicadores
   certos, prioridade visual, e se `st.bar_chart` (nativo, cru) deve virar
   componente customizado com a paleta do sistema (atualmente os gráficos
   nativos do Streamlit não seguem 100% a régua de cor do design system —
   ajuste pendente, provavelmente via Plotly/Altair com cores explícitas
   `NAVY`/`GREEN` de `modules/styles.py`).
3. **Popup de pendências entre sessões** — implementado via persistência em
   Spaces (`key_pending_table`), mas o fluxo de resolução de fato (o
   selectbox de "produto unificado correspondente") só funciona com os
   arquivos RMC/BASE_COMPLETA carregados na sessão atual — se o usuário loga
   e só vê o alerta sem re-upload, ele não consegue resolver ainda. Avaliar
   se vale a pena guardar os últimos arquivos processados em cache/Spaces
   para permitir resolver pendências sem precisar re-upload toda sessão.
4. **Boto3/Spaces não testado contra bucket real** — a lógica foi validada
   por leitura cuidadosa e é o mesmo padrão usado nos outros projetos de
   Mariano, mas peço rodar um teste real de escrita/leitura assim que houver
   credenciais disponíveis (pasta `Cota RMC/` dentro do bucket já existente).
5. **`dias_periodo_snapshot`** — hoje é um campo manual na aba Configurações
   (o usuário informa quantos dias o export cobre, ex: ~92 para
   Mai+Jun+Jul). Não há como inferir isso do arquivo de forma confiável
   (não há coluna de data linha a linha, só o rodapé de filtro que foi
   descartado na limpeza). Vale considerar parsear esse rodapé antes de
   descartá-lo, para pré-preencher esse campo automaticamente — não fiz
   isso porque o formato do texto do rodapé pode variar entre exports.

## Decisões de negócio já fechadas (não redecidir)

- RMC é a âncora do universo de produtos, não a BASE_COMPLETA inteira.
- Alias de correção manual tem chave `(ean, laboratorio_rmc)`, não só `ean`.
- Item RMC sem correspondência confirmada fica **inativo** (fora de tabelas
  e cálculos) até resolução manual — nunca aparece com dado incompleto/errado.
- Oportunidade = `venda_loja == 0 E estoque_loja == 0`.
- Risco de Ruptura = `estoque_loja < demanda_diária × dias_cobertura × 0.85`
  (margem de segurança confirmada, editável em tela).
- Pedido Sugerido = `max(0, demanda_diária × dias_cobertura − estoque_loja)`.
- Múltiplos laboratórios RMC suportados desde já; coluna/filtro de
  "Laboratório RMC" só aparece na UI quando há mais de um carregado.
- Sem integração com base de lojas da Rede (decisão explícita) — CNPJ
  aparece cru na tabela e no dashboard.
- Bucket Spaces compartilhado com outros projetos, isolado sob o prefixo
  `Cota RMC/` (configurável via `SPACES_PROJECT_PREFIX`).

## Arquivos de origem esperados (schema real, validado)

- `BASE_COMPLETA.xlsx`: `FCC | EAN | DESCRIÇÃO MARCOS` — 1 linha por
  variante de EAN, ~2.235 produtos unificados cobrindo ~7.095 EANs.
- Tabela RMC (por laboratório): `Família | EAN / DUN | Produto |
  Quantidade Solicitada | R$ Unitário Bruto | Desconto | R$ Total Líquido |
  R$ Total Líquido Total`. Preço RMC usado = `R$ Total Líquido` (unitário,
  já líquido de desconto).
- Movimentação de lojas (export GPS Farma): `Nome_Estado | cnpj |
  CodigoBarras | NomeProduto | Laboratório | Fat. líquido | % CMV | % MLB |
  Quantidade | QtdEstoque`. Contém rodapé de metadados de export a ser
  descartado (já tratado em `data_loader.py`).

## Dados de exemplo para testes (fixtures)

O repositório é público — os arquivos reais (BASE_COMPLETA.xlsx, tabela RMC,
export de movimentação das lojas) nunca são versionados nem devem ser. Para
testes locais e validação de fluxo sem depender dos arquivos reais nem expor
dado real, existe um gerador de dados 100% sintéticos:

- `tests/fixtures/gerar_dados_exemplo.py` — gera `BASE_COMPLETA_exemplo.xlsx`,
  `TABELA_RMC_exemplo.xlsx` e `DADOS_LOJAS_exemplo.xlsx` em
  `tests/fixtures/`, com os mesmos nomes de coluna/aba dos arquivos reais e
  seed fixo (42) — os dados gerados são reprodutíveis (os bytes do `.xlsx`
  em si não são idênticos entre execuções porque o openpyxl embute timestamp
  de criação no arquivo, mas o conteúdo/DataFrame é sempre o mesmo).
- Reproduz de propósito os casos-limite que o app precisa tratar: ~13 EANs
  da tabela RMC sem correspondência na base (pendências de matching),
  rodapé de export (linha "Total", linha vazia, 2 linhas de metadados),
  duplicidade cnpj+EAN com `NomeProduto` diferente (testa a agregação),
  casos de Oportunidade e Risco de Ruptura, outliers de estoque e % CMV
  negativos.
- Regenerar quando precisar: `python tests/fixtures/gerar_dados_exemplo.py`
  (sobrescreve os 3 arquivos, idempotente).

**Para Claude Code, em tarefas futuras:** prefira esses arquivos de exemplo
para validação de rotina (rodar o pipeline em Python, testar a UI, conferir
o efeito de uma mudança) — é mais rápido e não depende do usuário informar
caminho de arquivo real. Isso é uma preferência, não uma regra rígida: se a
tarefa exigir volume ou característica que só o dado real tem (ex: teste de
performance com as ~61 mil linhas do arquivo de lojas real) ou for uma
confirmação final antes de uma mudança considerada crítica, peça ao usuário
o caminho dos arquivos reais, como já vinha sendo feito antes deste gerador
existir.

## Como rodar localmente

```bash
pip install -r requirements.txt
cp .env.example .env            # preencher credenciais Spaces
cp .streamlit/secrets.toml.example .streamlit/secrets.toml  # preencher login
streamlit run app.py
```
