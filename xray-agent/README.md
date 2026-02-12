# XRay Agent

Агент для управления XRay на VPN серверах.

## Описание

Легковесный микросервис, который устанавливается на каждом VPN сервере и управляет локальным XRay сервером. Получает команды от Core API и выполняет их.

## Возможности

- Регистрация в Core API при запуске
- Получение команд от Core API (добавить/удалить пользователя)
- Управление XRay конфигурацией
- Автоматическая перезагрузка XRay после изменений
- Отправка метрик в Core API каждые 30 секунд
- Мониторинг статуса XRay каждые 10 секунд
- Отправка событий в Core API при проблемах

## Установка

### Переменные окружения

```bash
# Core API connection
CORE_API_URL=http://core-api:8000
AGENT_API_KEY=your-agent-api-key
SERVER_ID=1

# Agent settings
AGENT_PORT=8080
AGENT_URL=https://your-vpn-server-ip:8080

# XRay Configuration
XRAY_CONFIG_PATH=/etc/xray/config.json
XRAY_RELOAD_COMMAND=docker exec xray-server xray -test -config /etc/xray/config.json && docker exec xray-server kill -SIGHUP 1
```

## API Endpoints

### Health Check

```bash
GET /health
```

### Получить команду (вызывается Core API)

```bash
POST /commands
Headers:
  X-API-Key: agent-api-key
Body:
{
  "command": "add_user" | "remove_user",
  "user_uuid": "uuid-string",
  "email": "user@example.com"  # optional
}
```

### Статус агента

```bash
GET /status
Headers:
  X-API-Key: agent-api-key
```

## Развертывание

Агент должен быть установлен на каждом VPN сервере. При запуске он автоматически регистрируется в Core API.

## Безопасность

- Все endpoints требуют API ключ в заголовке `X-API-Key`
- API ключ настраивается через переменную окружения `AGENT_API_KEY`
- Коммуникация с Core API должна быть через HTTPS (в продакшене)
