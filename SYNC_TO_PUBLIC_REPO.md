# Синхронизация с публичным репозиторием

VPN-нода также опубликована в отдельном репо для установки в один клик:

**https://github.com/Alexjptz/hv-node**

## Как обновить публичный репо после изменений

```bash
# 1. Скопировать изменения в standalone-репо
cp -r /root/HomeVPN/vpn-server/* /root/hv-node/

# 2. Обновить URL в install-vpn-server.sh (если изменили)
# GITHUB_REPO и sparse-checkout должны указывать на hv-node

# 3. Закоммитить и запушить
cd /root/hv-node
git add .
git status  # проверить изменения
git commit -m "Update: описание изменений"
git push origin main
```

## Важно

- Скрипты в hv-node настроены на репо `Alexjptz/hv-node`
- Не перезаписывайте GITHUB_REPO в install-vpn-server.sh при копировании
- vpn-server/ здесь — для локальной разработки, docker-compose использует ./vpn-server/xray-agent
