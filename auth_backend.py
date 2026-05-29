from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False


PROJECT_ROOT = Path(__file__).resolve().parent
DASHBOARD_DIR = PROJECT_ROOT / "docs" / "crm-metas"
DATA_JSON = DASHBOARD_DIR / "data.json"
INDEX_HTML = DASHBOARD_DIR / "index.html"
SESSION_COOKIE = "bugbee_crm_session"
SESSION_HOURS = 12
PBKDF2_ITERATIONS = 210_000


@dataclass(frozen=True)
class AuthSettings:
    db_path: Path
    secret_key: str
    admin_email: str
    admin_password: str
    cookie_secure: bool


def load_auth_settings() -> AuthSettings:
    """Carrega configuracoes de autenticacao sem expor segredos em logs ou HTML."""
    load_dotenv(PROJECT_ROOT / ".env")
    secret_key = os.getenv("AUTH_SECRET_KEY", "")
    if not secret_key:
        raise RuntimeError("AUTH_SECRET_KEY ausente. Defina um segredo forte antes de iniciar o backend.")

    db_path = Path(os.getenv("AUTH_DB_PATH", PROJECT_ROOT / "data" / "auth.sqlite3"))
    return AuthSettings(
        db_path=db_path,
        secret_key=secret_key,
        admin_email=os.getenv("ADMIN_EMAIL", "").strip().lower(),
        admin_password=os.getenv("ADMIN_PASSWORD", ""),
        cookie_secure=os.getenv("AUTH_COOKIE_SECURE", "true").lower() in {"1", "true", "yes", "sim"},
    )


settings = load_auth_settings()
app = FastAPI(title="Bugbee CRM Auth")


def utc_now() -> datetime:
    """Retorna o horario atual em UTC para sessoes e auditoria."""
    return datetime.now(timezone.utc)


def db_connect() -> sqlite3.Connection:
    """Abre uma conexao SQLite com row factory padronizado."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Cria as tabelas de usuarios e auditoria se ainda nao existirem."""
    with db_connect() as conn:
        conn.executescript(
            """
            create table if not exists users (
              id integer primary key autoincrement,
              email text not null unique,
              name text not null default '',
              role text not null check(role in ('admin', 'viewer')),
              status text not null check(status in ('active', 'inactive')) default 'active',
              password_hash text,
              created_at text not null,
              updated_at text not null,
              last_login_at text
            );

            create table if not exists audit_events (
              id integer primary key autoincrement,
              actor_email text,
              action text not null,
              target_email text,
              created_at text not null,
              ip text
            );
            """
        )


def hash_password(password: str) -> str:
    """Gera hash PBKDF2 com salt aleatorio para senha de admin."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Compara uma senha com o hash armazenado usando tempo constante."""
    if not stored_hash:
        return False
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def sign_payload(payload: dict[str, Any]) -> str:
    """Assina um payload JSON para uso como cookie de sessao."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = hmac.new(settings.secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def unsign_payload(token: str | None) -> dict[str, Any] | None:
    """Valida e decodifica um cookie assinado."""
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    expected = hmac.new(settings.secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    padding = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode((body + padding).encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(utc_now().timestamp()):
        return None
    return payload


def create_session(user: sqlite3.Row) -> str:
    """Cria um token de sessao para um usuario ativo."""
    exp = utc_now() + timedelta(hours=SESSION_HOURS)
    return sign_payload(
        {
            "sub": int(user["id"]),
            "email": user["email"],
            "role": user["role"],
            "csrf": secrets.token_urlsafe(24),
            "exp": int(exp.timestamp()),
        }
    )


def set_session_cookie(response: Response, token: str) -> None:
    """Aplica o cookie de sessao com flags seguras."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove o cookie de sessao."""
    response.delete_cookie(SESSION_COOKIE, path="/")


def audit(action: str, actor_email: str | None = None, target_email: str | None = None, ip: str | None = None) -> None:
    """Registra uma acao administrativa ou de login sem armazenar dados sensiveis."""
    with db_connect() as conn:
        conn.execute(
            "insert into audit_events(actor_email, action, target_email, created_at, ip) values (?, ?, ?, ?, ?)",
            (actor_email, action, target_email, utc_now().isoformat(), ip),
        )


def bootstrap_admin() -> None:
    """Cria ou atualiza o admin inicial informado por variaveis de ambiente."""
    if not settings.admin_email or not settings.admin_password:
        return
    now = utc_now().isoformat()
    password_hash = hash_password(settings.admin_password)
    with db_connect() as conn:
        existing = conn.execute("select id from users where email = ?", (settings.admin_email,)).fetchone()
        if existing:
            conn.execute(
                """
                update users
                   set role = 'admin', status = 'active', password_hash = ?, updated_at = ?
                 where email = ?
                """,
                (password_hash, now, settings.admin_email),
            )
        else:
            conn.execute(
                """
                insert into users(email, name, role, status, password_hash, created_at, updated_at)
                values (?, ?, 'admin', 'active', ?, ?, ?)
                """,
                (settings.admin_email, "Administrador", password_hash, now, now),
            )


init_db()
bootstrap_admin()


def current_user(request: Request) -> sqlite3.Row | None:
    """Busca o usuario atual a partir do cookie e confirma status no banco."""
    session = unsign_payload(request.cookies.get(SESSION_COOKIE))
    if not session:
        return None
    with db_connect() as conn:
        user = conn.execute(
            "select * from users where id = ? and email = ? and status = 'active'",
            (session.get("sub"), session.get("email")),
        ).fetchone()
    return user


def current_session(request: Request) -> dict[str, Any] | None:
    """Retorna a sessao assinada se ela for valida."""
    return unsign_payload(request.cookies.get(SESSION_COOKIE))


async def form_data(request: Request) -> dict[str, str]:
    """Lê dados de formulario urlencoded sem depender de multipart."""
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1].strip() for key, values in parsed.items()}


def escape(value: Any) -> str:
    """Escapa valores para HTML."""
    return html.escape("" if value is None else str(value), quote=True)


def page(title: str, body: str) -> HTMLResponse:
    """Renderiza uma pagina simples usando a identidade visual do painel."""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow" />
  <title>{escape(title)} | Bugbee CRM</title>
  <style>
    @font-face {{ font-family: Rubrik; src: url('/fonts/Rubrik.otf') format('opentype'); font-weight: 400; }}
    @font-face {{ font-family: Rubrik; src: url('/fonts/Rubrik SemiBold.otf') format('opentype'); font-weight: 600; }}
    @font-face {{ font-family: Rubrik; src: url('/fonts/Rubrik Bold.otf') format('opentype'); font-weight: 700; }}
    :root {{ --ink:#073747; --ink2:#0b4555; --orange:#aa4a1f; --cream:#fbf7f1; --line:#d8d0c8; --text:#102a34; --muted:#60717a; --white:#fff; --red:#b42318; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:var(--cream); color:var(--text); font-family:Rubrik,Arial,sans-serif; letter-spacing:0; }}
    main {{ max-width:1040px; margin:0 auto; padding:28px; }}
    header {{ background:var(--ink); color:var(--white); padding:22px 24px; border-radius:4px; display:flex; justify-content:space-between; align-items:center; gap:16px; }}
    h1 {{ margin:0; font-size:28px; line-height:1.05; }}
    a {{ color:var(--ink); font-weight:700; }}
    .box {{ background:var(--white); border:1px solid var(--line); border-radius:4px; margin-top:18px; padding:20px; }}
    label {{ display:block; font-size:13px; font-weight:700; margin:12px 0 6px; color:var(--ink); }}
    input, select {{ width:100%; padding:12px; border:1px solid var(--line); border-radius:3px; font:inherit; background:#fff; }}
    button, .btn {{ display:inline-block; border:0; background:var(--orange); color:#fff; padding:11px 14px; border-radius:3px; font:inherit; font-weight:700; text-decoration:none; cursor:pointer; }}
    .btn.secondary, button.secondary {{ background:var(--ink2); }}
    .btn.danger, button.danger {{ background:var(--red); }}
    .actions {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:14px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; background:#fff; }}
    th {{ background:var(--ink); color:#fff; text-align:left; font-size:13px; padding:10px; }}
    td {{ border-top:1px solid var(--line); padding:10px; font-size:14px; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    .error {{ color:var(--red); font-weight:700; }}
    @media (max-width:760px) {{ main {{ padding:14px; }} header {{ display:block; }} table {{ font-size:13px; }} }}
  </style>
</head>
<body><main>{body}</main></body></html>"""
    )


def require_user(request: Request) -> sqlite3.Row | RedirectResponse:
    """Retorna usuario logado ou redireciona para login consultivo."""
    user = current_user(request)
    if user:
        return user
    return RedirectResponse("/login", status_code=303)


def require_admin(request: Request) -> sqlite3.Row | RedirectResponse:
    """Retorna admin logado ou redireciona para login admin."""
    user = current_user(request)
    if user and user["role"] == "admin":
        return user
    return RedirectResponse("/admin/login", status_code=303)


def verify_csrf(request: Request, submitted: str) -> bool:
    """Confere token CSRF armazenado na sessao assinada."""
    session = current_session(request)
    return bool(session and hmac.compare_digest(str(session.get("csrf", "")), submitted))


@app.get("/health")
def health() -> JSONResponse:
    """Endpoint simples para healthcheck de deploy."""
    return JSONResponse({"ok": True})


@app.get("/login")
def viewer_login_page(request: Request, error: str = "") -> Response:
    """Exibe login consultivo por email."""
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    message = "<p class='error'>Email nao autorizado ou usuario inativo.</p>" if error else ""
    return page(
        "Acesso",
        f"""
        <header><h1>Acesso ao Painel CRM</h1><a class="btn secondary" href="/admin/login">Admin</a></header>
        <section class="box">
          {message}
          <form method="post" action="/login">
            <label for="email">Email autorizado</label>
            <input id="email" name="email" type="email" autocomplete="email" required />
            <div class="actions"><button type="submit">Entrar</button></div>
          </form>
          <p class="muted">O acesso consultivo usa apenas emails cadastrados e ativos pelo admin.</p>
        </section>
        """,
    )


@app.post("/login")
async def viewer_login(request: Request) -> RedirectResponse:
    """Autentica usuario consultivo por email cadastrado e ativo."""
    data = await form_data(request)
    email = data.get("email", "").lower()
    with db_connect() as conn:
        user = conn.execute(
            "select * from users where email = ? and role = 'viewer' and status = 'active'",
            (email,),
        ).fetchone()
        if not user:
            audit("viewer_login_denied", target_email=email, ip=request.client.host if request.client else None)
            return RedirectResponse("/login?error=1", status_code=303)
        conn.execute("update users set last_login_at = ? where id = ?", (utc_now().isoformat(), user["id"]))
    audit("viewer_login", actor_email=email, ip=request.client.host if request.client else None)
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, create_session(user))
    return response


@app.get("/admin/login")
def admin_login_page(request: Request, error: str = "") -> Response:
    """Exibe login administrativo com email e senha."""
    user = current_user(request)
    if user and user["role"] == "admin":
        return RedirectResponse("/admin/users", status_code=303)
    message = "<p class='error'>Email, senha ou permissao invalidos.</p>" if error else ""
    return page(
        "Admin",
        f"""
        <header><h1>Admin CRM</h1><a class="btn secondary" href="/login">Acesso consultivo</a></header>
        <section class="box">
          {message}
          <form method="post" action="/admin/login">
            <label for="email">Email admin</label>
            <input id="email" name="email" type="email" autocomplete="email" required />
            <label for="password">Senha</label>
            <input id="password" name="password" type="password" autocomplete="current-password" required />
            <div class="actions"><button type="submit">Entrar</button></div>
          </form>
        </section>
        """,
    )


@app.post("/admin/login")
async def admin_login(request: Request) -> RedirectResponse:
    """Autentica admin por senha."""
    data = await form_data(request)
    email = data.get("email", "").lower()
    password = data.get("password", "")
    with db_connect() as conn:
        user = conn.execute(
            "select * from users where email = ? and role = 'admin' and status = 'active'",
            (email,),
        ).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            audit("admin_login_denied", target_email=email, ip=request.client.host if request.client else None)
            return RedirectResponse("/admin/login?error=1", status_code=303)
        conn.execute("update users set last_login_at = ? where id = ?", (utc_now().isoformat(), user["id"]))
    audit("admin_login", actor_email=email, ip=request.client.host if request.client else None)
    response = RedirectResponse("/admin/users", status_code=303)
    set_session_cookie(response, create_session(user))
    return response


@app.post("/logout")
def logout() -> RedirectResponse:
    """Encerra a sessao atual."""
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response


@app.get("/")
def dashboard(request: Request) -> Response:
    """Serve o dashboard HTML somente para usuarios autenticados."""
    user_or_redirect = require_user(request)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    if not INDEX_HTML.exists():
        return page("Painel indisponivel", "<header><h1>Painel indisponivel</h1></header><section class='box'>Gere o dashboard antes de acessar.</section>")
    content = INDEX_HTML.read_text(encoding="utf-8")
    logout_bar = """
    <form method="post" action="/logout" style="position:fixed;right:14px;bottom:14px;z-index:20">
      <button type="submit" style="border:0;background:#073747;color:#fff;padding:10px 12px;border-radius:3px;font-weight:700">Sair</button>
    </form>
    """
    return HTMLResponse(content.replace("</body>", f"{logout_bar}</body>"))


@app.get("/data.json")
def dashboard_data(request: Request) -> Response:
    """Entrega dados agregados somente para usuarios autenticados."""
    user_or_redirect = require_user(request)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    if not DATA_JSON.exists():
        return JSONResponse({"error": "data_not_found"}, status_code=404)
    return JSONResponse(json.loads(DATA_JSON.read_text(encoding="utf-8")))


@app.get("/fonts/{filename}")
def fonts(filename: str) -> Response:
    """Serve fontes locais usadas no painel."""
    safe_name = Path(filename).name
    font_path = DASHBOARD_DIR / "fonts" / safe_name
    if not font_path.exists():
        return PlainTextResponse("not found", status_code=404)
    return Response(font_path.read_bytes(), media_type="font/otf")


@app.get("/admin/users")
def admin_users(request: Request) -> Response:
    """Lista usuarios e exibe formularios de gestao para admin."""
    admin_or_redirect = require_admin(request)
    if isinstance(admin_or_redirect, RedirectResponse):
        return admin_or_redirect
    session = current_session(request) or {}
    csrf = escape(session.get("csrf", ""))
    with db_connect() as conn:
        users = conn.execute("select * from users order by role, email").fetchall()
    rows = "\n".join(
        f"""
        <tr>
          <td>{escape(user['email'])}</td>
          <td>{escape(user['name'])}</td>
          <td>{escape(user['role'])}</td>
          <td>{escape(user['status'])}</td>
          <td>{escape(user['last_login_at'] or '')}</td>
          <td><a href="/admin/users/{int(user['id'])}/edit">Editar</a></td>
        </tr>
        """
        for user in users
    )
    return page(
        "Usuarios",
        f"""
        <header>
          <h1>Gestao de Usuarios</h1>
          <form method="post" action="/logout"><button class="secondary" type="submit">Sair</button></form>
        </header>
        <section class="box">
          <h2>Novo usuario</h2>
          <form method="post" action="/admin/users">
            <input type="hidden" name="csrf" value="{csrf}" />
            <label>Email</label><input name="email" type="email" required />
            <label>Nome</label><input name="name" />
            <label>Perfil</label>
            <select name="role"><option value="viewer">viewer</option><option value="admin">admin</option></select>
            <label>Status</label>
            <select name="status"><option value="active">active</option><option value="inactive">inactive</option></select>
            <label>Senha, somente se perfil admin</label><input name="password" type="password" autocomplete="new-password" />
            <div class="actions"><button type="submit">Criar usuario</button><a class="btn secondary" href="/">Ver painel</a></div>
          </form>
        </section>
        <section class="box">
          <h2>Usuarios cadastrados</h2>
          <table>
            <thead><tr><th>Email</th><th>Nome</th><th>Perfil</th><th>Status</th><th>Ultimo acesso</th><th></th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        """,
    )


@app.post("/admin/users")
async def admin_create_user(request: Request) -> RedirectResponse:
    """Cria usuario viewer ou admin a partir do painel administrativo."""
    admin_or_redirect = require_admin(request)
    if isinstance(admin_or_redirect, RedirectResponse):
        return admin_or_redirect
    data = await form_data(request)
    if not verify_csrf(request, data.get("csrf", "")):
        return RedirectResponse("/admin/users", status_code=303)
    email = data.get("email", "").lower()
    role = data.get("role", "viewer")
    status = data.get("status", "active")
    password = data.get("password", "")
    if role not in {"admin", "viewer"} or status not in {"active", "inactive"} or not email:
        return RedirectResponse("/admin/users", status_code=303)
    password_hash = hash_password(password) if role == "admin" and password else None
    now = utc_now().isoformat()
    with db_connect() as conn:
        conn.execute(
            """
            insert into users(email, name, role, status, password_hash, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(email) do update set
              name = excluded.name,
              role = excluded.role,
              status = excluded.status,
              password_hash = coalesce(excluded.password_hash, users.password_hash),
              updated_at = excluded.updated_at
            """,
            (email, data.get("name", ""), role, status, password_hash, now, now),
        )
    audit("user_upsert", actor_email=admin_or_redirect["email"], target_email=email, ip=request.client.host if request.client else None)
    return RedirectResponse("/admin/users", status_code=303)


@app.get("/admin/users/{user_id}/edit")
def admin_edit_user_page(user_id: int, request: Request) -> Response:
    """Exibe formulario de edicao de usuario."""
    admin_or_redirect = require_admin(request)
    if isinstance(admin_or_redirect, RedirectResponse):
        return admin_or_redirect
    session = current_session(request) or {}
    csrf = escape(session.get("csrf", ""))
    with db_connect() as conn:
        user = conn.execute("select * from users where id = ?", (user_id,)).fetchone()
    if not user:
        return RedirectResponse("/admin/users", status_code=303)
    role_options = "".join(
        f"<option value='{role}' {'selected' if user['role'] == role else ''}>{role}</option>" for role in ("viewer", "admin")
    )
    status_options = "".join(
        f"<option value='{status}' {'selected' if user['status'] == status else ''}>{status}</option>" for status in ("active", "inactive")
    )
    return page(
        "Editar usuario",
        f"""
        <header><h1>Editar Usuario</h1><a class="btn secondary" href="/admin/users">Voltar</a></header>
        <section class="box">
          <form method="post" action="/admin/users/{int(user['id'])}/edit">
            <input type="hidden" name="csrf" value="{csrf}" />
            <label>Email</label><input name="email" type="email" value="{escape(user['email'])}" required />
            <label>Nome</label><input name="name" value="{escape(user['name'])}" />
            <label>Perfil</label><select name="role">{role_options}</select>
            <label>Status</label><select name="status">{status_options}</select>
            <label>Nova senha, somente admin e somente se quiser trocar</label><input name="password" type="password" autocomplete="new-password" />
            <div class="actions"><button type="submit">Salvar</button></div>
          </form>
          <form method="post" action="/admin/users/{int(user['id'])}/delete" class="actions">
            <input type="hidden" name="csrf" value="{csrf}" />
            <button class="danger" type="submit">Excluir usuario</button>
          </form>
        </section>
        """,
    )


@app.post("/admin/users/{user_id}/edit")
async def admin_update_user(user_id: int, request: Request) -> RedirectResponse:
    """Atualiza cadastro, perfil, status e senha opcional do usuario."""
    admin_or_redirect = require_admin(request)
    if isinstance(admin_or_redirect, RedirectResponse):
        return admin_or_redirect
    data = await form_data(request)
    if not verify_csrf(request, data.get("csrf", "")):
        return RedirectResponse("/admin/users", status_code=303)
    email = data.get("email", "").lower()
    role = data.get("role", "viewer")
    status = data.get("status", "active")
    password = data.get("password", "")
    if role not in {"admin", "viewer"} or status not in {"active", "inactive"} or not email:
        return RedirectResponse("/admin/users", status_code=303)
    if int(admin_or_redirect["id"]) == user_id:
        role = "admin"
        status = "active"
    password_hash = hash_password(password) if role == "admin" and password else None
    with db_connect() as conn:
        if password_hash:
            conn.execute(
                "update users set email = ?, name = ?, role = ?, status = ?, password_hash = ?, updated_at = ? where id = ?",
                (email, data.get("name", ""), role, status, password_hash, utc_now().isoformat(), user_id),
            )
        else:
            conn.execute(
                "update users set email = ?, name = ?, role = ?, status = ?, updated_at = ? where id = ?",
                (email, data.get("name", ""), role, status, utc_now().isoformat(), user_id),
            )
    audit("user_update", actor_email=admin_or_redirect["email"], target_email=email, ip=request.client.host if request.client else None)
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/delete")
async def admin_delete_user(user_id: int, request: Request) -> RedirectResponse:
    """Exclui usuario, protegendo contra autoexclusao do admin logado."""
    admin_or_redirect = require_admin(request)
    if isinstance(admin_or_redirect, RedirectResponse):
        return admin_or_redirect
    data = await form_data(request)
    if not verify_csrf(request, data.get("csrf", "")):
        return RedirectResponse("/admin/users", status_code=303)
    if int(admin_or_redirect["id"]) == user_id:
        return RedirectResponse("/admin/users", status_code=303)
    with db_connect() as conn:
        user = conn.execute("select email from users where id = ?", (user_id,)).fetchone()
        if user:
            conn.execute("delete from users where id = ?", (user_id,))
            audit("user_delete", actor_email=admin_or_redirect["email"], target_email=user["email"], ip=request.client.host if request.client else None)
    return RedirectResponse("/admin/users", status_code=303)
