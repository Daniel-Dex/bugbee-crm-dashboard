# Publicacao do painel CRM Bugbee

Este projeto esta preparado para publicar o painel em GitHub Pages sem expor credenciais da API.

## Arquivos publicos

Somente a pasta `docs/` deve ser publicada no GitHub Pages. Ela contem:

- `docs/crm-metas/index.html`
- `docs/crm-metas/data.json`
- fontes da identidade visual em `docs/crm-metas/fonts/`

O painel publico exibe apenas metricas consolidadas:

- Realizado 2025
- Meta 2026
- Realizado 2026
- taxa de recompra
- atingimento da meta

## Credenciais

As credenciais da API nao devem ir para o HTML, JSON, README, logs ou qualquer arquivo versionado.

Cadastre estes secrets no repositorio GitHub:

- `MAGAZORD_BASE_URL`
- `MAGAZORD_API_KEY`
- `MAGAZORD_API_SECRET`

Caminho no GitHub:

`Settings > Secrets and variables > Actions > New repository secret`

## GitHub Pages

Ative o GitHub Pages por Actions:

`Settings > Pages > Build and deployment > Source > GitHub Actions`

O workflow `.github/workflows/crm_dashboard.yml` executa diariamente, busca os dados na API usando GitHub Secrets e publica a pasta `docs/`.

A rotina atual roda durante a madrugada em America/Bahia, usa retry com backoff para falhas temporarias, respeita a paginacao `page/limit` da API e publica apenas metricas agregadas do painel.

O workflow semanal nao publica mais artefatos com planilhas, apresentacoes ou logs. Qualquer saida com dado pessoal deve permanecer fora do repositorio publico e fora dos artefatos de Actions.

Depois do primeiro deploy, o painel deve ficar em:

`https://<usuario-ou-org>.github.io/<repositorio>/crm-metas/`

## Comandos esperados quando Git e GitHub CLI estiverem instalados

```powershell
git init
git add .gitignore .github docs src tools analise_recompra.py projecao_positivacao.py gerar_painel_crm.py requirements.txt README.md PUBLICACAO_GITHUB.md
git commit -m "Publica painel CRM Bugbee"
gh repo create <usuario-ou-org>/<repositorio> --private --source . --remote origin --push
gh secret set MAGAZORD_BASE_URL
gh secret set MAGAZORD_API_KEY
gh secret set MAGAZORD_API_SECRET
```

Use `--public` no `gh repo create` somente se o codigo tambem puder ser publico. Mesmo em repositorio publico, as credenciais continuam protegidas em GitHub Secrets.

## Auditoria local realizada

Foi feita uma busca nos arquivos versionaveis e na pasta publica `docs/` por termos sensiveis como:

- `MAGAZORD_API_KEY`
- `MAGAZORD_API_SECRET`
- `Authorization`
- `Bearer`
- `Basic`
- `token`
- `secret`
- `senha`
- `password`
- `cliente_id`
- `email`
- `telefone`
- `cpf`
- `cnpj`

Resultado: nenhum segredo ou dado pessoal foi encontrado na pasta publica `docs/`.
