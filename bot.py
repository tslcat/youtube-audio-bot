import os
import logging
import json
from tempfile import TemporaryDirectory
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import asyncio

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_FILE = "/tmp/scheduled_channels.json"
HISTORY_FILE = "/tmp/download_history.json"

def load_data(file):
    if os.path.exists(file):
        try:
            with open(file, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_data(data, file):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

def main_keyboard():
    keyboard = [
        [KeyboardButton("📥 立即下载音频"), KeyboardButton("⏰ 设置定时下载")],
        [KeyboardButton("📋 查看定时任务"), KeyboardButton("❌ 取消定时任务")],
        [KeyboardButton("❓ 帮助")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 YouTube 音频下载 Bot\n请选择功能或发送链接：", reply_markup=main_keyboard())

# ==================== 增强下载函数 ====================
async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url=None, is_scheduled=False):
    if not url and update:
        url = update.message.text.strip()

    if not url or not ("youtube.com" in url or "youtu.be" in url):
        if update:
            await update.message.reply_text("❌ 请发送有效的 YouTube 链接")
        return

    msg = await update.message.reply_text("⏳ 正在处理...") if update else None

    # 定时任务使用更低音质
    quality = '64' if is_scheduled else '128'

    try:
        with TemporaryDirectory(dir="/tmp") as tmpdir:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{tmpdir}/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': quality,      # 关键：降低音质
                }],
                'quiet': True,
                'noplaylist': True,
                'socket_timeout': 60,
                'retries': 5,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info.get('id')
                filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            title = info.get('title', '未知音频')

            chat_id = update.effective_chat.id if update else None

            if file_size_mb > 48:
                await msg.edit_text(f"📦 文件较大（{file_size_mb:.1f}MB），尝试压缩后发送...")
                # 再次压缩
                compressed = filename.replace('.mp3', '_compressed.mp3')
                os.system(f'ffmpeg -i "{filename}" -b:a 48k -y "{compressed}" 2>/dev/null || cp "{filename}" "{compressed}"')
                filename = compressed
                file_size_mb = os.path.getsize(filename) / (1024 * 1024)

            if file_size_mb > 48:
                await msg.edit_text("❌ 文件仍然过大，无法发送（超过 Telegram 限制）")
                os.remove(filename)
                return

            await context.bot.send_audio(
                chat_id=chat_id,
                audio=open(filename, 'rb'),
                title=title,
                filename=os.path.basename(filename),
                caption=f"🎵 {title}\n🔗 {url}\n📏 {file_size_mb:.1f}MB"
            )

            os.remove(filename)
            if msg:
                await msg.edit_text("✅ 发送完成！")

    except Exception as e:
        logger.error(f"Download error: {e}")
        if msg:
            await msg.edit_text(f"❌ 处理失败：{str(e)[:120]}")

# ==================== 菜单处理 ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text in ["📥 立即下载音频", "立即下载音频"]:
        await update.message.reply_text("请直接发送 YouTube 视频链接：", reply_markup=main_keyboard())
    elif text in ["⏰ 设置定时下载", "设置定时下载"]:
        await update.message.reply_text("请发送频道链接（例如 https://www.youtube.com/@xxxx）", reply_markup=main_keyboard())
    elif "youtube.com" in text or "youtu.be" in text:
        await download_audio(update, context, url=text)
    else:
        await update.message.reply_text("请选择菜单按钮或发送 YouTube 链接", reply_markup=main_keyboard())

def main():
    app = Application.builder().token(TOKEN.strip()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot 已启动 | 低音质防413模式")
    app.run_polling()

if __name__ == '__main__':
    main()