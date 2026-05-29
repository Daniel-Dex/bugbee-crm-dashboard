# Operacao da API para o painel CRM

## Dados fundamentais para os calculos

O painel de metas CRM precisa apenas de pedidos validos. O cadastro completo de clientes nao e necessario para os calculos atuais.

Campos efetivamente usados:

- `id` ou `codigo`: identificador do pedido.
- `pessoaId`: identificador do comprador.
- `dataHora`: data do pedido.
- `valorTotal` ou equivalente: valor do pedido.
- `pedidoSituacao`: codigo da situacao do pedido.
- `pedidoSituacaoDescricao`: descricao da situacao do pedido.
- `pedidoSituacaoTipo`: tipo operacional da situacao.

Campos nao usados no painel:

- nome do cliente.
- CPF/CNPJ.
- email.
- telefone.
- endereco.
- detalhe de itens.
- cadastro de pessoas.
- nota fiscal.
- pagamentos.

## Limpeza aplicada

O painel chama somente `/v2/site/pedido`.

A chamada a `/v2/site/pessoa` foi removida do fluxo do dashboard porque `pessoaId` ja vem no pedido e e suficiente para contar clientes unicos, recompradores e taxa de recompra.

Mesmo quando a API retorna campos adicionais, o processamento transforma cada pedido em um schema minimo e descarta o restante antes dos calculos.

## Paginacao

O consumo segue a paginacao documentada da API:

- `limit`
- `page`
- `has_more`
- fallback por `len(items) < limit`

Tambem ha protecao contra loop de pagina repetida.

## Retry e rate limit

O client trata falhas temporarias com retry e backoff:

- `429`: respeita `Retry-After` quando enviado.
- `500`, `502`, `503`, `504`: tenta novamente com espera progressiva.
- falhas de rede: tenta novamente antes de falhar.

## Rotina diaria

O GitHub Actions roda diariamente durante a madrugada:

- `03:20` em America/Bahia.
- ate `6` tentativas por execucao.
- intervalo progressivo entre tentativas.
- deploy so acontece quando a geracao termina com sucesso.

## Principio de minimizacao

Qualquer nova metrica deve declarar antes:

- endpoint necessario.
- campos usados.
- por que o campo e fundamental.
- se contem PII.
- se pode ser agregado antes de publicar.

Campos com PII nao devem ser publicados, versionados ou enviados como artefato de Actions.
