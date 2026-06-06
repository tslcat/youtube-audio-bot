youtube-audio-bot

services:
  bot:
    image: tslcat/youtube-audio-bot:latest
    container_name: youtube-audio-bot
    environment:
      - TELEGRAM_TOKEN= # 🌟 在这里直接粘贴你的完整 Token
    restart: unless-stopped
    volumes:
      - /root/downloads:/tmp/downloads  # 可选：持久化下载目录（调试用）
