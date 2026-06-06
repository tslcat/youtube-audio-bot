import os
import logging
import json
from tempfile import TemporaryDirectory
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

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
    await update.message.reply_text("👋 YouTube 音频下载 Bot\n请选择下方按钮或发送链接：", reply_markup=main_keyboard())

# ==================== 增强版下载函数（增加重试） ====================
async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url=None, is_scheduled=False, retry=2):
    if not url and update:
        url = update.message.text.strip()

    if not url or not ("youtube.com" in url or "youtu.be" in url):
        if update:
            await update.message.reply_text("❌ 请发送有效的 YouTube 链接")
        return

    msg = await update.message.reply_text("⏳ 正在下载... (网络超时将自动重试)") if update else None

    for attempt in range(retry + 1):
        try:
            with TemporaryDirectory(dir="/tmp") as tmpdir:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'{tmpdir}/%(title)s.%(ext)s',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '128',
                    }],
                    'quiet': True,
                    'noplaylist': True,
                    'socket_timeout': 30,          # 增加超时时间
                    'retries': 5,                  # yt-dlp 内部重试
                    'fragment_retries': 5,
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    video_id = info.get('id')
                    filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

                file_size_mb = os.path.getsize(filename) / (1024 * 1024)
                title = info.get('title', '未知音频')

                chat_id = update.effective_chat.id if update else (context.job.chat_id if hasattr(context, 'job') else None)

                if file_size_mb > 48:
                    await context.bot.send_document(chat_id=chat_id, document=open(filename, 'rb'),
                                                  filename=os.path.basename(filename),
                                                  caption=f"🎵 {title}\n🔗 {url}")
                else:
                    await context.bot.send_audio(chat_id=chat_id, audio=open(filename, 'rb'),
                                               title=title, filename=os.path.basename(filename),
                                               caption=f"🎵 {title}\n🔗 {url}")

                os.remove(filename)
                if msg:
                    await msg.edit_text("✅ 下载发送完成！")
                return

        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed: {e}")
            if attempt < retry:
                await msg.edit_text(f"⚠️ 下载超时，正在第 {attempt+2} 次重试...") if msg else None
                await asyncio.sleep(5)
            else:
                error_text = f"❌ 下载失败（多次超时）\n可能是网络不稳定，请稍后重试。"
                if msg:
                    await msg.edit_text(error_text)
                else:
                    await context.bot.send_message(chat_id=chat_id, text=error_text)

# ==================== 定时任务 ====================
async def scheduled_download(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(DATA_FILE)
    for chat_id, channel_url in data.items():
        try:
            await context.bot.send_message(int(chat_id), "🔄 定时检查频道最新视频...")
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'playlist_items': '1'}) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if info and 'entries' in info and info['entries']:
                    latest = info['entries'][0]
                    latest_url = latest.get('url') or latest.get('webpage_url')
                    latest_id = latest.get('id')

                    history = load_data(HISTORY_FILE)
                    if chat_id in history and latest_id in history[chat_id]:
                        continue

                    await context.bot.send_message(int(chat_id), "🆕 发现新视频，开始下载...")
                    await download_audio(None, context, url=latest_url, is_scheduled=True)
        except Exception as e:
            logger.error(f"Scheduled error: {e}")

# ==================== 菜单处理 ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text in ["📥 立即下载音频", "立即下载音频"]:
        await update.message.reply_text("请直接发送 YouTube 视频链接：", reply_markup=main_keyboard())
    elif text in ["⏰ 设置定时下载", "设置定时下载"]:
        await update.message.reply_text("请发送要定时监控的**频道链接**：", reply_markup=main_keyboard())
    elif text in ["📋 查看定时任务", "查看定时任务"]:
        await update.message.reply_text("当前暂无定时任务（功能开发中）", reply_markup=main_keyboard())
    elif text in ["❌ 取消定时任务", "取消定时任务"]:
        await update.message.reply_text("已取消定时任务（功能开发中）", reply_markup=main_keyboard())
    elif text == "❓ 帮助":
        await start(update, context)
    elif "youtube.com" in text or "youtu.be" in text:
        await download_audio(update, context, url=text)
    else:
        await update.message.reply_text("请选择菜单或发送 YouTube 链接", reply_markup=main_keyboard())

def main():
    app = Application.builder().token(TOKEN.strip()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot 已启动 | 菜单模式 + 超时重试")
    app.run_polling()

if __name__ == '__main__':
    main()