# Automação semanal Bugbee

Automação para consultar a API da Magazord, tratar dados semanais de e-commerce, gerar planilhas atualizadas e produzir uma apresentação executiva semanal.

## Segurança

As credenciais nunca ficam no código. Configure somente por variáveis de ambiente:

```env
MAGAZORD_BASE_URL=
MAGAZORD_API_KEY=
MAGAZORD_API_SECRET=
```

Use `.env` apenas localmente. O arquivo `.env` está no `.gitignore` e não deve ser versionado.

## Estrutura

```text
src/
  config.py
  magazord_client.py
  extract.py
  transform.py
  calculations.py
  spreadsheet_updater.py
  presentation_generator.py
  charts.py
  history.py
  logs.py
  main.py
data/
  raw/
  processed/
  history/
  output/
  templates/
logs/
.github/workflows/weekly_presentation.yml
```

## Como rodar localmente

1. Crie um ambiente Python.
2. Instale dependências:

```bash
pip install -r requirements.txt
```

3. Crie um `.env` local com as variáveis reais:

```bash
cp .env.example .env
```

4. Execute:

```bash
python -m src.main
```

Para apenas criar a estrutura de pastas sem exigir credenciais:

```bash
python -m src.main --no-api
```

Se alguma variável obrigatória estiver ausente, o script retorna apenas o nome da variável ausente, sem expor valores.

## GitHub Actions

O workflow `.github/workflows/weekly_presentation.yml` está configurado para rodar toda segunda-feira às 11:00 UTC, equivalente a 08:00 em `America/Sao_Paulo`.

Configure estes secrets no repositório:

- `MAGAZORD_BASE_URL`
- `MAGAZORD_API_KEY`
- `MAGAZORD_API_SECRET`

Os arquivos gerados são publicados como artifacts da execução:

- `apresentacao_semanal_bugbee_YYYY-MM-DD.pptx`
- `planilha_dados_semanal_bugbee_YYYY-MM-DD.xlsx`
- `log_execucao_YYYY-MM-DD.txt`

Também são criadas cópias com nome fixo:

- `apresentacao_semanal_bugbee_atual.pptx`
- `planilha_dados_semanal_bugbee_atual.xlsx`

## Metodologia

### Documentação Magazord

A implementação foi estruturada com base na documentação oficial em <https://docs.api.magazord.com.br/>. A documentação informa uso de `BasicAuth`, paginação por `page/limit` em endpoints v2, paginação por `offset/limit` em `/api/v1/listEstoque`, consulta de pedidos em `/api/v2/site/pedido`, pessoas em `/api/v2/site/pessoa`, produtos em `/api/v2/site/produto`, produto completo em `/api/v3/produtos/query`, estoque em `/api/v1/listEstoque`, formas de pagamento em `/api/v2/site/forma-recebimento` e canais de venda em `/api/v2/site/estoque/projecaoEstoque/canaisVenda`.

### Extração

`src/magazord_client.py` concentra as chamadas à API. O cliente:

- usa autenticação via variáveis de ambiente;
- registra apenas endpoint e parâmetros seguros;
- não registra credenciais;
- trata paginação;
- registra avisos quando um endpoint falha;
- permite ajuste modular de endpoints sem mexer no restante do pipeline.

### Tratamento

`src/transform.py` normaliza pedidos, itens e estoque em colunas padronizadas. Como payloads reais podem variar por configuração da loja, o transformador usa uma função `pick()` para mapear nomes alternativos comuns sem quebrar a execução.

### Cálculos

`src/calculations.py` calcula:

- faturamento;
- pedidos;
- itens vendidos;
- ticket médio;
- peças por pedido;
- desconto médio quando preço cheio está disponível;
- rankings de produto/categoria;
- alertas simples de estoque baixo.

Indicadores sem dados suficientes ficam indisponíveis e devem ser registrados no log. O script não inventa métricas.

### Planilhas

`src/spreadsheet_updater.py` gera uma planilha com abas:

- Base API Tratada
- Base Consolidada
- Indicadores Semanais
- Comparativo Semanal
- Produtos e Categorias
- Estoque e Giro
- Dados para Apresentação

A versão inicial gera um arquivo consolidado novo, sem sobrescrever as planilhas originais. A partir da validação dos payloads reais da API, o próximo passo é mapear cada aba existente da planilha base para atualização preservando fórmulas e formatação.

### Apresentação

`src/presentation_generator.py` gera uma apresentação `.pptx` editável com o padrão visual Bugbee usado no relatório deste projeto: capa, resumo executivo e visão geral de vendas. A estrutura está pronta para ampliar os slides conforme os campos reais da API forem confirmados.

### Logs

Os logs ficam em `logs/` e registram:

- data/hora;
- período analisado;
- endpoints consultados;
- quantidades extraídas;
- arquivos gerados;
- avisos e erros.

Credenciais não são salvas em logs, planilhas, apresentações ou documentação.

## Observações importantes

- Funil, sessões, mídia paga, metas e margem dependem de endpoints/exports específicos. Se esses dados não estiverem disponíveis na API Magazord, a automação deve usar fonte complementar ou registrar a limitação.
- O primeiro ciclo com credenciais reais deve ser tratado como homologação: validar payloads reais, ajustar mapeamento de campos e reconciliar os números contra a planilha base atual.
