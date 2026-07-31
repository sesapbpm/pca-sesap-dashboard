# Dashboard PCA — SESAP/RN

Painel gerencial dos Planos de Contratações Anuais publicados no PNCP pela
SESAP/RN e suas unidades com autonomia de compra.

## Abrir o painel

Execute `abrir_dashboard.ps1`. O navegador abrirá em:

`http://localhost:8765`

## Atualizar a base

Execute `atualizar_dados.ps1`. A rotina:

1. identifica os CNPJs filiais da raiz `08.241.754`;
2. consulta os anos disponíveis no PNCP;
3. baixa os planos e itens;
4. atualiza `data/pca_sesap.json` e `data/pca_sesap.csv`.

As consultas são somente leitura e usam os endpoints oficiais
`https://pncp.gov.br/api/pncp/v1`.

## Conteúdo do painel

- indicadores de valor, itens, unidades e ticket médio;
- evolução anual;
- composição por categoria;
- ranking de matriz e filiais;
- calendário mensal das contratações;
- tabela detalhada, busca e exportação do recorte filtrado.
- fase 2 do ciclo: PGC, compras iniciadas, valores homologados e contratos;
- vínculos classificados como confirmados, prováveis ou não encontrados;
- contingência entre a API do Contratos.gov.br e as rotas do PNCP.

Os valores representam planejamento publicado, não execução orçamentária.
