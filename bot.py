import os
import logging
import asyncio
from tempfile import TemporaryDirectory
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

# 加载环境变量
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# 日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 你好！发送 YouTube 视频链接，我会帮你下载音频并发送回来。\n\n"
        "支持单个视频或短视频。"
    )

async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not ("youtube.com" in url or "youtu.be" in url):
        await update.message.reply_text("❌ 请发送有效的 YouTube 链接")
        return

    msg = await update.message.reply_text("⏳ 正在下载音频，请稍等...")

    try:
        with TemporaryDirectory(dir="/tmp") as tmpdir:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{tmpdir}/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

            if not os.path.exists(filename):
                await msg.edit_text("❌ 下载失败")
                return

            file_size = os.path.getsize(filename) / (1024*1024)
            if file_size > 48:  # Telegram 限制约50MB
                await msg.edit_text(f"❌ 文件太大（{file_size:.1f}MB），Telegram 无法发送")
                os.remove(filename)
                return

            await msg.edit_text(f"✅ 下载完成，正在发送...\n文件：{info.get('title', '未知')}")
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=open(filename, 'rb'),
                title=info.get('title', 'YouTube Audio'),
                filename=os.path.basename(filename),
                caption=f"🎵 {info.get('title', '音频')}\n🔗 {url}"
            )

            # 发送完成后删除文件
            os.remove(filename)
            await msg.edit_text("✅ 音频已发送，文件已清理")

    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ 处理失败：{str(e)[:200]}")

def main():
    if not TOKEN:
        logger.error("请在 .env 文件中设置 TELEGRAM_TOKEN")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_audio))

    print("🤖 Bot 已启动...")
    app.run_polling()

if __name__ == '__main__':
    main()