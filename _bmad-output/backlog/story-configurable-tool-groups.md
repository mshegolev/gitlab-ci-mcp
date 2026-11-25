---
tracker_id: ""
id: 1
type: story
title: "Выборочное отключение групп MCP-инструментов"
parent: none
covers: []
sources: []
companions: []
after: []
assignee: ""
refined: true
hitl: false
risk: medium
---

# Выборочное отключение групп MCP-инструментов

## Description

Инженер может отключить ненужные группы MCP-инструментов через конфигурацию сервера, чтобы сократить список инструментов, который клиенту нужно учитывать; без настройки доступны все группы. Неверная настройка может скрыть нужные инструменты, поэтому по умолчанию сохраняется полный набор.

## Requirements

1. **Сохранение полного набора по умолчанию**
   **Given** переменная `GITLAB_DISABLED_TOOL_GROUPS` не задана или содержит только пробелы
   **When** MCP-сервер запускается
   **Then** клиенту объявляются инструменты всех шести групп из таблицы ниже
   **And** поведение по умолчанию совпадает с текущим

2. **Отключение выбранных групп**
   **Given** в `GITLAB_DISABLED_TOOL_GROUPS` перечислены через запятую одна или несколько известных групп
   **When** MCP-сервер запускается
   **Then** клиенту не объявляются инструменты перечисленных групп
   **And** клиенту объявляются все инструменты остальных групп
   **And** пробелы вокруг имён групп и разделителей не меняют результат
   **And** пустые элементы и повторные имена игнорируются
   **And** если после удаления пустых элементов настройка не содержит имён групп, отключённых групп нет

3. **Стабильные имена групп и состав**
   **Given** настройка содержит идентификаторы из таблицы
   **When** владелец сервера указывает одну или несколько групп для отключения
   **Then** каждый идентификатор отключает только перечисленные для него инструменты
   **And** ни один инструмент не принадлежит более чем одной группе

   | Идентификатор | Инструменты |
   | --- | --- |
   | `pipelines` | `gitlab_list_pipelines`, `gitlab_get_pipeline`, `gitlab_get_pipeline_jobs`, `gitlab_get_job_log`, `gitlab_list_job_artifacts`, `gitlab_get_job_artifact`, `gitlab_trigger_pipeline`, `gitlab_retry_pipeline`, `gitlab_cancel_pipeline`, `gitlab_pipeline_health` |
   | `schedules` | `gitlab_list_schedules`, `gitlab_create_schedule`, `gitlab_update_schedule`, `gitlab_delete_schedule` |
   | `branches_tags` | `gitlab_list_branches`, `gitlab_list_tags`, `gitlab_compare_branches` |
   | `merge_requests` | `gitlab_list_merge_requests`, `gitlab_get_merge_request`, `gitlab_get_merge_request_changes`, `gitlab_create_merge_request`, `gitlab_merge_mr` |
   | `repository` | `gitlab_get_file`, `gitlab_list_repository_tree`, `gitlab_project_info` |
   | `package` | `gitlab_ci_mcp_check_updates` |

4. **Разрешено отключить все группы**
   **Given** `GITLAB_DISABLED_TOOL_GROUPS` перечисляет все шесть известных групп
   **When** MCP-сервер запускается
   **Then** сервер запускается без объявленных tools

5. **Ошибка неизвестной группы**
   **Given** настройка содержит имя, которого нет среди поддерживаемых групп
   **When** MCP-сервер запускается
   **Then** запуск завершается понятной ошибкой конфигурации с неизвестным именем
   **And** сервер не стартует с молча проигнорированной настройкой

6. **Документирование настройки**
   **Given** владелец сервера настраивает MCP
   **When** он читает раздел Configuration в README
   **Then** там указаны переменная `GITLAB_DISABLED_TOOL_GROUPS`, все шесть идентификаторов с составом групп, правила для пустых элементов и повторов, и пример отключения нескольких групп

**Verify:** выполнить MCP `tools/list` с отсутствующей, пустой, содержащей только пробелы, одиночной и множественной настройкой; проверить обрезку пробелов, пустые элементы и повторы на значении ` , pipelines , , pipelines `; проверить неизвестное имя и настройку со всеми шестью группами. Сравнить результат с таблицей выше, проверить понятную ошибку запуска для неизвестной группы и сверить описание настройки с разделом Configuration в README.

## Boundaries

- Must not change: если настройка отсутствует, клиент по-прежнему видит все текущие инструменты.
- Must not change: поведение и схемы оставшихся включёнными инструментов.
- Must not change: права доступа GitLab и доступность самих GitLab API; настройка управляет только объявлением групп MCP-инструментов клиенту.

## References

- README — https://github.com/mshegolev/gitlab-ci-mcp/blob/main/README.md#features, Features (tool names and groups)
- README — https://github.com/mshegolev/gitlab-ci-mcp/blob/main/README.md#configuration, Configuration (environment variable convention)

## Notes

- Decision: 2026-11-25 — все группы включены по умолчанию; выборочное отключение задаётся конфигурацией через переменную окружения.
- Decision: 2026-11-25 — пустые элементы и повторы в списке игнорируются; допускается отключить все группы и запустить сервер с нулём tools.
