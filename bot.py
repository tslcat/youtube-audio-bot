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
    await update.message.reply_text(
        "👋 **YouTube 音频下载 Bot**\n\n请选择下方按钮操作：", 
        reply_markup=main_keyboard()
    )

# ==================== 下载函数 ====================
async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url=None, is_scheduled=False):
    if not url and update:
        url = update.message.text.strip()

    if not url or not ("youtube.com" in url or "youtu.be" in url):
        if update:
            await update.message.reply_text("❌ 请发送有效的 YouTube 链接", reply_markup=main_keyboard())
        return

    msg = await update.message.reply_text("⏳ 正在处理...") if update else None

    quality = '64' if is_scheduled else '96'

    try:
        with TemporaryDirectory(dir="/tmp") as tmpdir:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{tmpdir}/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': quality,
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

            # 记录历史
            if is_scheduled and video_id:
                history = load_data(HISTORY_FILE)
                chat_id = str(update.effective_chat.id) if update else "global"
                history.setdefault(chat_id, [])
                if video_id not in history[chat_id]:
                    history[chat_id].append(video_id)
                    save_data(history, HISTORY_FILE)

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            title = info.get('title', '未知音频')

            chat_id = update.effective_chat.id if update else None

            if file_size_mb > 48:
                await msg.edit_text("⚠️ 文件过大，尝试压缩...")
                compressed = filename.replace('.mp3', '_low.mp3')
                os.system(f'ffmpeg -i "{filename}" -b:a 48k "{compressed}" -y 2>/dev/null || true')
                if os.path.exists(compressed):
                    filename = compressed

            await context.bot.send_audio(
                chat_id=chat_id,
                audio=open(filename, 'rb'),
                title=title,
                filename=os.path.basename(filename),
                caption=f"🎵 {title}\n🔗 {url}"
            )

            os.remove(filename)
            if msg:
                await msg.edit_text("✅ 发送完成！")

    except Exception as e:
        logger.error(f"Error: {e}")
        if msg:
            await msg.edit_text(f"❌ 处理失败：{str(e)[:100]}")

# ==================== 定时任务 ====================
async def scheduled_download(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(DATA_FILE)
    for chat_id, channel_url in data.items():
        try:
            await context.bot.send_message(int(chat_id), "🔄 定时检查新视频...")
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'playlist_items': '1'}) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if info and 'entries' in info and info['entries']:
                    latest = info['entries'][0]
                    latest_url = latest.get('url') or latest.get('webpage_url')
                    latest_id = latest.get('id')

                    history = load_data(HISTORY_FILE)
                    if chat_id in history and latest_id in history[chat_id]:
                        continue

                    await context.bot.send_message(int(chat_id), f"🆕 发现新视频：{latest.get('title','未知')}")
                    await download_audio(None, context, url=latest_url, is_scheduled=True)
        except:
            pass

# ==================== 菜单按钮处理 ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text in ["📥 立即下载音频", "立即下载音频"]:
        await update.message.reply_text("✅ 请直接发送 YouTube **视频** 链接：", reply_markup=main_keyboard())
    
    elif text in ["⏰ 设置定时下载", "设置定时下载"]:
        await update.message.reply_text(
            "✅ 请发送**频道链接**（例如：\nhttps://www.youtube.com/@xxxx）\n\n"
            "设置后每24小时自动下载最新未下载视频。",
            reply_markup=main_keyboard()
        )
    
    elif text in ["📋 查看定时任务", "查看定时任务"]:
        data = load_data(DATA_FILE)
        if data:
            msg = "📋 当前定时任务：\n\n" + "\n".join([f"• {url}" for url in data.values()])
        else:
            msg = "暂无定时任务"
        await update.message.reply_text(msg, reply_markup=main_keyboard())
    
    elif text in ["❌ 取消定时任务", "取消定时任务"]:
        chat_id = str(update.effective_chat.id)
        data = load_data(DATA_FILE)
        if chat_id in data:
            del data[chat_id]
            save_data(data, DATA_FILE)
            await update.message.reply_text("✅ 已取消当前定时任务", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("当前没有定时任务", reply_markup=main_keyboard())
    
    elif text == "❓ 帮助":
        await start(update, context)
    
    elif "youtube.com" in text or "youtu.be" in text:
        await download_audio(update, context, url=text)
    
    else:
        await update.message.reply_text("请选择菜单功能或发送链接", reply_markup=main_keyboard())

def main():
    app = Application.builder().token(TOKEN.strip()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 定时任务
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(scheduled_download, interval=86400, first=60)

    print("🤖 Bot 已启动 | 完整菜单模式")
    app.run_polling()

if __name__ == '__main__':
    main()