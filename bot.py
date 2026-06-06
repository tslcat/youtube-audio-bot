import os
import logging
import json
import asyncio
from datetime import datetime
from tempfile import TemporaryDirectory
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, JobQueue
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 YouTube 音频下载 Bot\n\n"
        "命令：\n"
        "/download <视频链接> → 立即下载\n"
        "/schedule <频道链接> → 每24小时自动下载**最新未下载**视频\n"
        "/listschedule → 查看定时任务\n"
        "/removeschedule → 取消定时任务"
    )

# ==================== 核心下载函数 ====================
async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url=None, is_scheduled=False):
    if not url:
        url = update.message.text.strip()
    
    if not ("youtube.com" in url or "youtu.be" in url):
        if update:
            await update.message.reply_text("❌ 请发送有效的 YouTube 链接")
        return

    msg = None
    if update:
        msg = await update.message.reply_text("⏳ 正在处理...")

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
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info.get('id')
                filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

            # 记录已下载视频ID（仅定时任务记录）
            if is_scheduled and video_id:
                history = load_data(HISTORY_FILE)
                chat_id = str(update.effective_chat.id) if update else "scheduled"
                if chat_id not in history:
                    history[chat_id] = []
                if video_id not in history[chat_id]:
                    history[chat_id].append(video_id)
                    save_data(history, HISTORY_FILE)

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            title = info.get('title', '未知音频')

            if msg:
                await msg.edit_text(f"✅ 下载完成（{file_size_mb:.1f}MB），正在发送...")

            if file_size_mb > 48:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id if update else context.job.chat_id,
                    document=open(filename, 'rb'),
                    filename=os.path.basename(filename),
                    caption=f"🎵 {title}\n🔗 {url}"
                )
            else:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id if update else context.job.chat_id,
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
        error_msg = f"❌ 处理失败：{str(e)[:150]}"
        if msg:
            await msg.edit_text(error_msg)
        else:
            await context.bot.send_message(chat_id=context.job.chat_id, text=error_msg)

# ==================== 定时任务 ====================
async def scheduled_download(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(DATA_FILE)
    for chat_id, channel_url in list(data.items()):
        try:
            await context.bot.send_message(int(chat_id), text=f"🔄 开始检查频道最新视频...\n{channel_url}")
            
            # 获取频道最新视频
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'playlist_items': '1'}) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if 'entries' in info and info['entries']:
                    latest_url = info['entries'][0]['url']
                    latest_id = info['entries'][0]['id']
                    
                    # 检查是否已下载
                    history = load_data(HISTORY_FILE)
                    if chat_id in history and latest_id in history[chat_id]:
                        await context.bot.send_message(int(chat_id), text="✅ 已是最新视频，无需下载。")
                        continue
                    
                    await context.bot.send_message(int(chat_id), text="🆕 发现新视频，开始下载...")
                    await download_audio(None, context, url=latest_url, is_scheduled=True)
                else:
                    await context.bot.send_message(int(chat_id), text="⚠️ 无法获取频道最新视频")
        except Exception as e:
            logger.error(f"Scheduled task error: {e}")
            try:
                await context.bot.send_message(int(chat_id), text=f"❌ 定时任务出错：{str(e)[:100]}")
            except:
                pass

# ==================== 命令处理 ====================
async def schedule_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法: `/schedule <频道链接>`")
        return

    channel_url = context.args[0]
    chat_id = str(update.effective_chat.id)

    data = load_data(DATA_FILE)
    data[chat_id] = channel_url
    save_data(data, DATA_FILE)

    await update.message.reply_text(f"✅ 已设置定时任务！\n每24小时检查并下载**新视频**。\n频道：{channel_url}")

async def list_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data(DATA_FILE)
    if not data:
        await update.message.reply_text("当前没有定时任务。")
        return
    text = "📋 当前定时任务：\n\n"
    for url in data.values():
        text += f"• {url}\n"
    await update.message.reply_text(text)

async def remove_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data(DATA_FILE)
    if chat_id in data:
        del data[chat_id]
        save_data(data, DATA_FILE)
        await update.message.reply_text("✅ 已取消定时任务。")
    else:
        await update.message.reply_text("当前没有定时任务。")

def main():
    if not TOKEN or len(TOKEN.strip()) < 10:
        logger.error("TELEGRAM_TOKEN 无效")
        return

    app = Application.builder().token(TOKEN.strip()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", lambda u, c: download_audio(u, c)))
    app.add_handler(CommandHandler("schedule", schedule_channel))
    app.add_handler(CommandHandler("listschedule", list_schedule))
    app.add_handler(CommandHandler("removeschedule", remove_schedule))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_audio))

    # 定时任务
    job_queue = app.job_queue
    job_queue.run_repeating(scheduled_download, interval=86400, first=30)  # 每24小时

    print("🤖 Bot 已启动... 定时任务支持防重复下载")
    app.run_polling()

if __name__ == '__main__':
    main()