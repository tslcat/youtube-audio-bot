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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
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
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 YouTube 音频 Bot\n请选择功能：", reply_markup=main_keyboard())

# ==================== 进度更新（关键改进） ====================
async def send_progress(update, context, msg, status_text):
    try:
        await msg.edit_text(status_text, reply_markup=main_keyboard())
    except:
        pass

def progress_hook(d):
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '??')
        eta = d.get('_eta_str', '')
        logger.info(f"下载中: {percent} ETA: {eta}")
    elif d['status'] == 'finished':
        logger.info("下载完成 → 开始转 MP3")

# ==================== 下载函数（针对长视频优化） ====================
async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url=None, is_scheduled=False):
    if not url and update:
        url = update.message.text.strip()

    if not url or not ("youtube.com" in url or "youtu.be" in url):
        if update:
            await update.message.reply_text("❌ 请发送有效 YouTube 链接", reply_markup=main_keyboard())
        return

    msg = await update.message.reply_text("⏳ 正在获取视频信息...", reply_markup=main_keyboard())

    try:
        with TemporaryDirectory(dir="/tmp") as tmpdir:
            # 长视频优化配置
            quality = '64' if is_scheduled else '96'  # 定时任务用更低码率
            ydl_opts = {
                'format': 'bestaudio/best',                    # 仅最佳音频流
                'outtmpl': f'{tmpdir}/%(id)s_%(title).80s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': quality,
                    # FFmpeg 加速参数（对长视频很重要）
                    'postprocessor_args': [
                        '-acodec', 'libmp3lame',
                        '-q:a', quality,
                        '-threads', '0',           # 使用所有CPU核心
                        '-preset', 'fast'          # 更快编码
                    ],
                }],
                'quiet': False,
                'noplaylist': True,
                'socket_timeout': 120,             # 更长超时
                'retries': 5,
                'extractor_retries': 5,
                'concurrent_fragment_downloads': 4, # 并行分片下载（加速长视频）
                'progress_hooks': [progress_hook],
                'restrictfilenames': True,
                'windowsfilenames': True,
            }

            logger.info(f"开始处理长视频: {url}")
            await send_progress(update, context, msg, "⬇️ 正在下载音频流（长视频可能需要几分钟）...")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not filename.endswith('.mp3'):
                    filename = os.path.splitext(filename)[0] + '.mp3'

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            title = info.get('title', '音频')
            duration = info.get('duration', 0)
            duration_min = duration // 60

            logger.info(f"处理完成: {title} | 时长: {duration_min}分钟 | 大小: {file_size_mb:.1f}MB")

            await send_progress(update, context, msg, f"✅ 下载完成（{duration_min}分钟），正在发送...")

            send_kwargs = {
                'chat_id': update.effective_chat.id,
                'filename': os.path.basename(filename),
                'caption': f"🎵 {title}\n⏱ {duration_min}分钟\n🔗 {url}",
                'reply_markup': main_keyboard()
            }

            if file_size_mb > 48:
                await context.bot.send_document(document=open(filename, 'rb'), **send_kwargs)
            else:
                await context.bot.send_audio(audio=open(filename, 'rb'), title=title, **send_kwargs)

            os.remove(filename)
            await msg.edit_text(f"✅ 发送完成！\n🎵 {title} ({duration_min}分钟)", reply_markup=main_keyboard())

    except asyncio.TimeoutError:
        await msg.edit_text("⏱️ 处理超时（视频过长），请稍后重试或使用短视频", reply_markup=main_keyboard())
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        error_msg = str(e)[:180]
        await msg.edit_text(f"❌ 处理失败：{error_msg}\n\n💡 长视频建议：降低质量或分段下载", reply_markup=main_keyboard())

# ==================== 定时任务 ====================
async def scheduled_download(context: ContextTypes.DEFAULT_TYPE):
    data = load_data(DATA_FILE)
    for chat_id, channel_url in list(data.items()):
        try:
            await context.bot.send_message(int(chat_id), "🔄 检查频道最新视频...", reply_markup=main_keyboard())

            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'playlist_items': '1',
                'socket_timeout': 60,
                'retries': 3
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

            if info and 'entries' in info and info['entries']:
                latest = info['entries'][0]
                latest_url = latest.get('url') or latest.get('webpage_url')
                latest_id = latest.get('id')

                history = load_data(HISTORY_FILE)
                if chat_id not in history:
                    history[chat_id] = []
                if latest_id in history[chat_id]:
                    continue

                history[chat_id].append(latest_id)
                if len(history[chat_id]) > 30:
                    history[chat_id] = history[chat_id][-30:]
                save_data(history, HISTORY_FILE)

                await context.bot.send_message(int(chat_id), f"🆕 发现新视频，开始下载...", reply_markup=main_keyboard())
                await download_audio(None, context, url=latest_url, is_scheduled=True)
            else:
                await context.bot.send_message(int(chat_id), "⚠️ 未找到最新视频", reply_markup=main_keyboard())
        except Exception as e:
            logger.error(f"Scheduled error for {chat_id}: {e}")
            try:
                await context.bot.send_message(int(chat_id), "⚠️ 定时任务出错，稍后重试", reply_markup=main_keyboard())
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

    if app.job_queue:
        app.job_queue.run_repeating(scheduled_download, interval=86400, first=10)

    print("🤖 YouTube 音频 Bot 已启动 | 长视频下载能力大幅提升")
    app.run_polling()

if __name__ == '__main__':
    main()