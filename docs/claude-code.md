# gitlab-ci-mcp — подключение Claude Code

## Локальный режим: stdio

Для локального процесса нужен свой GitLab PAT с `api` scope и URL GitLab.
Путь проекта передаётся явно в вызовах tools.

```bash
# GITLAB_PAT должен быть загружен из secret manager в окружение
claude mcp add --transport stdio \
  --env GITLAB_URL=https://gitlab.example.com \
  --env GITLAB_TOKEN="$GITLAB_PAT" \
  gitlab -- uvx --from gitlab-ci-mcp gitlab-ci-mcp
```

`GITLAB_TOKEN` относится только к локальному stdio режиму. Один такой процесс
использует один PAT.

Для `.mcp.json` локального stdio сервера можно передавать секрет через
переменную окружения:

```json
{
  "mcpServers": {
    "gitlab": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "gitlab-ci-mcp", "gitlab-ci-mcp"],
      "env": {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "${GITLAB_PAT}"
      }
    }
  }
}
```

## Общий сервер: Streamable HTTP

Администратор запускает MCP на сервере за HTTPS reverse proxy:

```bash
MCP_TRANSPORT=streamable-http \
MCP_HTTP_HOST=127.0.0.1 \
MCP_HTTP_PORT=8000 \
GITLAB_URL=https://gitlab.example.com \
gitlab-ci-mcp
```

На клиенте у каждого разработчика должен быть свой PAT. Подавайте его в
кастомном HTTP-заголовке; PAT не передаётся как MCP tool argument и не должен
попадать в URL, общий `.mcp.json`, промпты или историю shell в открытом виде.

```bash
# GITLAB_PAT должен быть предоставлен secret manager в окружение
claude mcp add --transport http \
  --header "X-GitLab-Token: ${GITLAB_PAT}" \
  gitlab https://mcp.example.com/mcp
```

Либо настройте HTTP сервер в конфигурации клиента:

```json
{
  "mcpServers": {
    "gitlab": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "X-GitLab-Token": "${GITLAB_PAT}"
      }
    }
  }
}
```

Такой способ передаёт PAT непосредственно GitLab API как пользовательскую
учётную запись. Это custom-header auth, не стандартный OAuth flow MCP. Клиент
должен отправлять header на каждый запрос. Для текущих write tools необходим
GitLab PAT с `api` scope. HTTPS обязателен; прокси и tracing должны скрывать
`X-GitLab-Token` в логах.

Сервер проверяет наличие непустого header, а валидность PAT GitLab проверяет
при первом API вызове. Поэтому подключение и список tools могут работать с
отозванным токеном, но GitLab операция завершится ошибкой авторизации.

## Project scope и resources

Каждый GitLab tool требует `project_path`, если оператор явно не включил
совместимый fallback `GITLAB_ALLOW_DEFAULT_PROJECT=true` вместе с
`GITLAB_PROJECT_PATH`. Статические resources `gitlab://project/info` и
`gitlab://project/ci-config` не принимают путь проекта; они работают только
при включённом fallback и в HTTP режиме используют PAT текущего запроса.

## Остальные настройки

Проверка обновлений выключена по умолчанию. Установите
`MCP_GITLAB_UPDATE_CHECK_ENABLED=true`, чтобы включить явный вызов
`gitlab_ci_mcp_check_updates`; `false` или отсутствие переменной отключает
сетевой запрос к PyPI.

Для self-hosted GitLab за корпоративным proxy см. разделы **Configuration** и
**Self-hosted GitLab behind a corporate proxy** в [основном README](../README.md).

Подробности по credential isolation, кэшу, сроку жизни и ограничениям:
[docs/per-user-auth.md](per-user-auth.md).

## Проверка и удаление

```bash
claude mcp list
```

Локальный сервер удаляется командой `claude mcp remove gitlab`; удалённый —
так же, если он был добавлен с этим именем.
