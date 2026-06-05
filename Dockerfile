FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（yt-dlp 需要 ffmpeg）
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# 创建临时下载目录
RUN mkdir -p /tmp/downloads

CMD ["python", "bot.py"]