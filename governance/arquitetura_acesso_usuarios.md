# Arquitetura de acesso e gestao de usuarios

## Decisao tecnica

O painel atual roda em GitHub Pages, que e uma hospedagem estatica. Ele nao executa backend, nao guarda sessoes com seguranca e nao consegue proteger rotas por usuario.

Por isso, a gestao de usuarios nao deve ser implementada como JavaScript no HTML publico. Um login apenas no frontend seria facilmente contornavel e daria uma falsa sensacao de seguranca.

## Modelo recomendado

Criar uma camada backend entre o usuario e o painel:

- `admin`: login com email e senha.
- `viewer`: acesso consultivo por email, sem senha neste primeiro momento.
- painel admin para criar, editar, desativar e excluir usuarios.
- registro de auditoria para login, alteracao de usuario e exclusao.
- sessoes em cookie seguro, `HttpOnly`, `Secure`, `SameSite=Lax`.
- base de usuarios separada das credenciais da API MagaZord.

## Entidades

### users

- `id`
- `email`
- `name`
- `role`: `admin` ou `viewer`
- `status`: `active`, `disabled` ou `deleted`
- `created_at`
- `updated_at`
- `last_login_at`

### admin_credentials

- `user_id`
- `password_hash`
- `password_updated_at`

### login_tokens

- `id`
- `email`
- `token_hash`
- `expires_at`
- `used_at`
- `created_at`

### audit_events

- `id`
- `actor_user_id`
- `event_type`
- `target_user_id`
- `metadata_json`
- `created_at`

## Fluxo de acesso

### Admin

1. Admin acessa `/admin/login`.
2. Informa email e senha.
3. Backend valida hash da senha.
4. Backend cria sessao segura.
5. Admin acessa `/admin/users` para criar, editar, desativar ou excluir usuarios.

### Usuario consultivo

1. Usuario acessa `/login`.
2. Informa apenas email.
3. Backend valida se o email esta ativo.
4. Backend gera token temporario e envia link por email.
5. Usuario acessa o link e recebe sessao consultiva.

Observacao: mesmo sem senha, e necessario token temporario por email para provar posse da caixa postal. Liberar acesso apenas digitando qualquer email permitiria impersonacao.

## Escalabilidade

O modelo ja permite evoluir para:

- senha para viewers.
- verificacao em duas etapas.
- grupos e permissoes por painel.
- expiracao de sessao por politica.
- SSO corporativo.
- logs de auditoria para LGPD.

## Hospedagem recomendada

Opcoes adequadas:

- Cloudflare Pages + Cloudflare Workers + D1/KV.
- Vercel + serverless functions + Postgres.
- Render/Fly.io/Railway + FastAPI + Postgres.

GitHub Pages deve permanecer apenas para conteudo publico estatico. Se o painel passar a ser interno, a URL publica deve ser substituida por uma dessas opcoes com autenticacao real.
