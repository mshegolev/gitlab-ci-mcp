# gitlab-ci-mcp — установка в Claude Code

Пошаговая инструкция для подключения `gitlab-ci-mcp` к Claude Code CLI. После
установки ваш агент сможет работать с GitLab напрямую: смотреть пайплайны,
тригерить запуски, создавать MR, читать файлы из репозитория, анализировать
health CI/CD.

## 0. Что потребуется

| Требование | Как получить |
| --- | --- |
| **Claude Code CLI** | `npm install -g @anthropic-ai/claude-code` → `claude login` |
| **Python ≥ 3.10** | `python3 --version` (обычно уже есть) |
| **`uv` / `uvx`** | `brew install uv` (macOS) или `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **GitLab Personal Access Token** | GitLab → **Edit profile** → **Access Tokens** → name `claude-code-mcp`, scope `api`, срок по вашей политике |
| **Путь к default-проекту** | `namespace/project` из URL, например `my-org/my-repo` |

> **Self-hosted GitLab в корп-сети?** Проверьте что VPN поднят и `curl $GITLAB_URL/api/v4/version` работает из терминала. При необходимости см. раздел "Self-hosted" в основном README.

## 1. Установка — один из двух вариантов

### Вариант A. Через `claude mcp add` (быстрый старт)

Глобально для всех проектов:

```bash
claude mcp add gitlab uvx --from gitlab-ci-mcp gitlab-ci-mcp \
  --env GITLAB_URL=https://gitlab.example.com \
  --env GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx \
  --env GITLAB_PROJECT_PATH=my-org/my-repo
```

Флаги:

- `gitlab` — имя сервера в `claude mcp list` и в `/mcp`. Произвольное.
- `uvx --from gitlab-ci-mcp gitlab-ci-mcp` — команда запуска. `uvx` поднимает
  изолированное окружение для пакета с PyPI и выполняет его entry-point.
- `--env` — переменные среды, которые видит сам сервер (не shell).

### Вариант B. Через файл `.mcp.json` (рекомендуется для команды)

Положите в корень репозитория `.mcp.json`, **без токена** — чтобы файл можно
было закоммитить:

```json
{
  "mcpServers": {
    "gitlab": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "gitlab-ci-mcp", "gitlab-ci-mcp"],
      "env": {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "${GITLAB_TOKEN}",
        "GITLAB_PROJECT_PATH": "my-org/my-repo",
        "GITLAB_SSL_VERIFY": "true"
      }
    }
  }
}
```

Токен в `~/.zshrc` (или `~/.bash_profile`):

```bash
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx"
```

Для глобального применения положите тот же JSON в `~/.claude.json` в секцию
`mcpServers`.

## 2. Проверка

```bash
claude mcp list
```

Ожидаемый вывод:

```
gitlab: uvx --from gitlab-ci-mcp gitlab-ci-mcp - ✓ Connected
```

Если запущен Claude Code — перезапустите сессию (`/exit` → `claude`). Внутри
сессии:

```
/mcp
```

Должен показать `gitlab` со списком из **23 tools** и **2 resources**
(`gitlab://project/info`, `gitlab://project/ci-config`).

## 3. Первые запросы

Скопируйте в Claude Code — агент выберет правильный tool автоматически.

```
покажи последние 10 pipelines на master
```

```
какой health у master за 7 дней
```

```
что сломалось в последнем упавшем pipeline, покажи лог упавшего job
```

```
открой MR из feature/login в master с title "feat: login", описание из commit history
```

```
покажи .gitlab-ci.yml на master
```

## 4. Работа с несколькими проектами

Default-проект задаётся через `GITLAB_PROJECT_PATH`. Для ad-hoc запросов по
другому репо — передайте `project_path` в промпте:

```
покажи pipelines для проекта other-org/other-repo
```

Каждый tool принимает опциональный параметр `project_path`, который
переопределяет дефолт. Серверу по каждому `project_path` создаётся отдельная
кешированная HTTP-сессия — повторные вызовы быстрые.

## 5. Корпоративный self-hosted GitLab

Если GitLab во внутренней сети за локальным HTTP-прокси (типа `127.0.0.1:3128`),
пропишите в env сервера:

```json
{
  "GITLAB_NO_PROXY_DOMAINS": ".corp.example.com,gitlab.internal",
  "GITLAB_SSL_VERIFY": "false"
}
```

Сервер сам добавит эти домены в `NO_PROXY` и очистит `HTTP(S)_PROXY` из своего
процесса — запросы к GitLab пойдут напрямую.

## 6. Безопасность

- **Токен храните в env-переменной** или менеджере паролей, не в `.mcp.json` прямым текстом
- В `.mcp.json` используйте `"${GITLAB_TOKEN}"` — Claude Code подставит значение из shell
- PAT выдавайте с ограниченным сроком (3–6 месяцев), ротируйте
- При смене проекта/увольнении — отзовите токен в GitLab

## 7. Troubleshooting

### `✗ Failed to connect`

```bash
# 1. uvx вообще работает?
which uvx
uvx --version

# 2. пакет ставится?
uvx --from gitlab-ci-mcp gitlab-ci-mcp --help 2>&1 | head

# 3. вручную запустить — увидите настоящую ошибку
GITLAB_URL=https://gitlab.example.com \
GITLAB_TOKEN=glpat-xxx \
GITLAB_PROJECT_PATH=my-org/my-repo \
uvx --from gitlab-ci-mcp gitlab-ci-mcp
```

### `GitLab authentication failed`

- Токен истёк или не имеет scope `api` — пересоздайте
- Токен с пробелом/переносом в конце — перевыпустите и скопируйте через кнопку Copy

### `not found (HTTP 404)`

- Проверьте `GITLAB_PROJECT_PATH` — это `namespace/project` **целиком**, не только project name
- Убедитесь что ваша учётка имеет доступ к проекту

### `SSL: CERTIFICATE_VERIFY_FAILED`

Self-signed или корпоративный CA? Установите `GITLAB_SSL_VERIFY=false` в env
сервера (для dev). Для prod — добавьте корпоративный CA в системный trust store.

### Прокси режет запросы к `*.mts.ru` / `*.corp.*`

См. раздел **5. Self-hosted GitLab** выше — используйте `GITLAB_NO_PROXY_DOMAINS`.

### Claude Code не видит сервер после правки `.mcp.json`

- Проверьте синтаксис: `jq . .mcp.json`
- `/exit` → `claude` перезапускает сессию
- `claude mcp list` должен показать `gitlab` со статусом

### Нужно увидеть логи сервера

Сервер логирует в stderr. Запустите вручную с `--help`-обёрткой в shell и
посмотрите stderr, либо в Claude Code включите verbose режим MCP если клиент
его поддерживает.

## 8. Удаление

```bash
claude mcp remove gitlab
```

Или удалите секцию из `.mcp.json` / `~/.claude.json` и перезапустите сессию.

## Ссылки

- [Основной README](../README.md) — полный справочник по всем 23 tools
- [CHANGELOG](../CHANGELOG.md)
- [evaluations/questions.xml](../evaluations/questions.xml) — 22 тестовых промпта
- [Claude Code MCP docs](https://docs.anthropic.com/en/docs/claude-code/mcp)
