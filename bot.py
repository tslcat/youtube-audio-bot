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
        "发送视频链接即可下载。\n"
        "如遇到验证问题，请使用 Cookies 模式（见帮助）。",
        reply_markup=main_keyboard()
    )

async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not ("youtube.com" in url or "youtu.be" in url):
        await update.message.reply_text("❌ 请发送有效的 YouTube 链接", reply_markup=main_keyboard())
        return

    msg = await update.message.reply_text("⏳ 正在下载...")

    try:
        cookies_file = "/tmp/cookies.txt" if os.path.exists("/tmp/cookies.txt") else None

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'/tmp/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '96',
            }],
            'quiet': True,
            'noplaylist': True,
            'socket_timeout': 60,
            'retries': 5,
        }

        if cookies_file:
            ydl_opts['cookiefile'] = cookies_file

        with TemporaryDirectory(dir="/tmp") as tmpdir:
            ydl_opts['outtmpl'] = f'{tmpdir}/%(title)s.%(ext)s'
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            title = info.get('title', '未知音频')

            if file_size_mb > 48:
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
            await msg.edit_text("✅ 发送完成！")

    except Exception as e:
        logger.error(f"Error: {e}")
        error_str = str(e)
        if "Sign in to confirm" in error_str:
            await msg.edit_text("❌ YouTube 需要验证\n\n请使用 /cookies 命令上传 cookies.txt 文件")
        else:
            await msg.edit_text(f"❌ 处理失败：{error_str[:150]}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "❓ 帮助":
        await start(update, context)
    else:
        await download_audio(update, context)

def main():
    app = Application.builder().token(TOKEN.strip()).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot 已启动")
    app.run_polling()

if __name__ == '__main__':
    main()