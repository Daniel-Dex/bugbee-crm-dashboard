# Backend de acesso do Painel CRM

Esta camada protege o painel de metas com autenticacao real no servidor. Ela substitui o acesso direto ao GitHub Pages quando for publicada em um provedor com backend.

## Como funciona

- O admin entra por `/admin/login` com email e senha.
- O admin gerencia usuarios em `/admin/users`.
- Usuarios consultivos entram por `/login` usando apenas email cadastrado e ativo.
- O painel principal fica em `/`.
- O arquivo `data.json` agregado so e entregue para usuario autenticado.
- Credenciais da API Magazord continuam fora do navegador.

## Variaveis de ambiente

```env
AUTH_SECRET_KEY=gere_um_segredo_longo_e_unico
ADMIN_EMAIL=admin@empresa.com
ADMIN_PASSWORD=senha_forte_do_admin
AUTH_COOKIE_SECURE=true
AUTH_DB_PATH=./data/auth.sqlite3
```

Em producao, mantenha `AUTH_COOKIE_SECURE=true` e use HTTPS.

## Rodar localmente

```bash
pip install -r requirements.txt
uvicorn auth_backend:app --host 127.0.0.1 --port 8000
```

Depois acesse:

- `http://127.0.0.1:8000/admin/login`
- `http://127.0.0.1:8000/login`

## Banco de usuarios

O banco SQLite local fica em `data/auth.sqlite3` por padrao e nao deve ser versionado. O `.gitignore` ja ignora arquivos `data/*.sqlite`, `data/*.sqlite3` e `data/*.db`.

Campos principais:

- `email`
- `name`
- `role`: `admin` ou `viewer`
- `status`: `active` ou `inactive`
- `password_hash`: usado apenas para admins
- `last_login_at`

## Regras de seguranca

- Senhas de admin usam PBKDF2 com salt aleatorio.
- Sessao usa cookie assinado, `HttpOnly`, `SameSite=Lax` e `Secure` em producao.
- Acoes administrativas usam token CSRF.
- Usuarios inativos perdem acesso mesmo com cookie antigo.
- O admin logado nao pode excluir ou desativar a si mesmo pelo painel.

## Proximo passo de publicacao

Para o painel deixar de ser publico, publique este backend em um provedor que suporte servidor Python, como Render, Fly.io, Railway, VPS ou container. Depois aponte o analista para a URL do backend, nao para o GitHub Pages.
