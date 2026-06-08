import os
import logging
from tempfile import TemporaryDirectory
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def main_keyboard():
    keyboard = [
        [KeyboardButton("📥 立即下载音频")],
        [KeyboardButton("❓ 帮助")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **YouTube 音频下载 Bot**\n\n"
        "点击下方按钮或直接发送 YouTube 视频链接即可下载音频。",
        reply_markup=main_keyboard()
    )

async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # 提取链接
    url = text
    if text.startswith("📥"):
        await update.message.reply_text("请发送 YouTube 视频链接：", reply_markup=main_keyboard())
        return

    if not ("youtube.com" in url or "youtu.be" in url):
        await update.message.reply_text("❌ 请发送有效的 YouTube 链接", reply_markup=main_keyboard())
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
                    'preferredquality': '96',   # 平衡音质和大小
                }],
                'quiet': True,
                'noplaylist': True,
                'socket_timeout': 60,
                'retries': 5,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            title = info.get('title', '未知音频')

            if file_size_mb > 48:
                await msg.edit_text(f"📦 文件较大（{file_size_mb:.1f}MB），以文档形式发送...")
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
            await msg.edit_text("✅ 下载发送完成！")

    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ 处理失败：{str(e)[:150]}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "❓ 帮助":
        await start(update, context)
    elif "youtube.com" in text or "youtu.be" in text:
        await download_audio(update, context)
    else:
        await download_audio(update, context)   # 尝试作为链接处理

def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN 未设置")
        return

    app = Application.builder().token(TOKEN.strip()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot 已启动 | 简洁模式（仅立即下载）")
    app.run_polling()

if __name__ == '__main__':
    main()