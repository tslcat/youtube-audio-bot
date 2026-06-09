import os
import logging
import json
import asyncio
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
    await update.message.reply_text("👋 YouTube 音频 Bot\n请选择功能：", reply_markup=main_keyboard())

# ==================== 下载函数 ====================
async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url=None, is_scheduled=False):
    if not url and update:
        url = update.message.text.strip()

    if not url or not ("youtube.com" in url or "youtu.be" in url):
        if update:
            await update.message.reply_text("❌ 请发送有效 YouTube 链接", reply_markup=main_keyboard())
        return

    msg = await update.message.reply_text("⏳ 正在处理...") if update else None

    try:
        with TemporaryDirectory(dir="/tmp") as tmpdir:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{tmpdir}/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '64' if is_scheduled else '96',
                }],
                'quiet': True,
                'noplaylist': True,
                'socket_timeout': 30,
                'retries': 3,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

            file_size = os.path.getsize(filename) / (1024*1024)
            title = info.get('title', '音频')

            if file_size > 48:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=open(filename, 'rb'),
                    filename=os.path.basename(filename),
                    caption=f"🎵 {title}\n🔗 {url}"
                )
            else:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=open(filename, 'rb'),
                    title=title,
                    filename=os.path.basename(filename),
                    caption=f"🎵 {title}\n🔗 {url}"
                )

            os.remove(filename)
            if msg:
                await msg.edit_text("✅ 发送完成！")

    except Exception as e:
        logger.error(f"Download error: {e}")
        if msg:
            await msg.edit_text(f"❌ 处理失败：{str(e)[:80]}")

# ==================== 定时任务（加强超时保护） ====================
async def scheduled_download(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(DATA_FILE)
    for chat_id, channel_url in list(data.items()):
        try:
            await context.bot.send_message(int(chat_id), "🔄 检查频道最新视频...")

            # 增加超时保护
            ydl_opts = {
                'quiet': True, 
                'extract_flat': True, 
                'playlist_items': '1',
                'socket_timeout': 20,
                'retries': 2
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False, timeout=30)

            if info and 'entries' in info and info['entries']:
                latest = info['entries'][0]
                latest_url = latest.get('url') or latest.get('webpage_url')
                latest_id = latest.get('id')

                history = load_data(HISTORY_FILE)
                if chat_id in history and latest_id in history[chat_id]:
                    continue

                await context.bot.send_message(int(chat_id), f"🆕 发现新视频，开始下载...")
                await download_audio(None, context, url=latest_url, is_scheduled=True)
            else:
                await context.bot.send_message(int(chat_id), "⚠️ 未找到最新视频")
        except asyncio.TimeoutError:
            await context.bot.send_message(int(chat_id), "⏱️ 检查超时，稍后重试")
        except Exception as e:
            logger.error(f"Scheduled error for {chat_id}: {e}")
            try:
                await context.bot.send_message(int(chat_id), "⚠️ 定时任务出错，稍后自动重试")
            except:
                pass

# ==================== 菜单处理 ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text in ["📥 立即下载音频", "立即下载音频"]:
        await update.message.reply_text("请发送 YouTube 视频链接：", reply_markup=main_keyboard())

    elif text in ["⏰ 设置定时下载", "设置定时下载"]:
        await update.message.reply_text(
            "✅ 请直接发送**频道链接**（例如 https://www.youtube.com/@xxxx）", 
            reply_markup=main_keyboard()
        )

    elif text in ["📋 查看定时任务", "查看定时任务"]:
        data = load_data(DATA_FILE)
        msg = "📋 当前定时任务：\n" + "\n".join([f"• {v}" for v in data.values()]) if data else "暂无定时任务"
        await update.message.reply_text(msg, reply_markup=main_keyboard())

    elif text in ["❌ 取消定时任务", "取消定时任务"]:
        chat_id = str(update.effective_chat.id)
        data = load_data(DATA_FILE)
        if chat_id in data:
            del data[chat_id]
            save_data(data, DATA_FILE)
            await update.message.reply_text("✅ 已取消定时任务", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("当前没有定时任务", reply_markup=main_keyboard())

    elif text == "❓ 帮助":
        await start(update, context)

    elif "youtube.com" in text or "youtu.be" in text:
        await download_audio(update, context, url=text)

    else:
        await update.message.reply_text("请选择菜单或发送链接", reply_markup=main_keyboard())

def main():
    app = Application.builder().token(TOKEN.strip()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 定时任务
    if app.job_queue:
        app.job_queue.run_repeating(scheduled_download, interval=86400, first=10)

    print("🤖 Bot 已启动 | 定时下载已优化")
    app.run_polling()

if __name__ == '__main__':
    main()