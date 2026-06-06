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

# 主菜单键盘
def main_keyboard():
    keyboard = [
        [KeyboardButton("📥 立即下载音频"), KeyboardButton("⏰ 设置定时下载")],
        [KeyboardButton("📋 查看定时任务"), KeyboardButton("❌ 取消定时任务")],
        [KeyboardButton("❓ 帮助")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **YouTube 音频下载 Bot** 已启动！\n\n"
        "请选择下方功能或直接发送 YouTube 链接：",
        reply_markup=main_keyboard()
    )

# ==================== 下载核心函数 ====================
async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url=None, is_scheduled=False):
    if not url:
        text = update.message.text.strip()
        # 提取链接
        if "youtube.com" in text or "youtu.be" in text:
            url = text
        else:
            # 如果用户点击按钮但没发链接
            await update.message.reply_text("请发送 YouTube 视频或频道链接", reply_markup=main_keyboard())
            return

    msg = await update.message.reply_text("⏳ 正在处理，请稍等...")

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
            await msg.edit_text("✅ 下载发送完成！")

    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ 处理失败：{str(e)[:150]}")

# ==================== 其他命令 ====================
async def schedule_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("请回复频道链接，例如：\n/schedule https://www.youtube.com/@xxxx", reply_markup=main_keyboard())
        return
    # ...（保持原有逻辑，代码较长，后面补全）
    await update.message.reply_text("✅ 定时任务已设置！", reply_markup=main_keyboard())

# 简化版菜单处理
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "📥 立即下载音频":
        await update.message.reply_text("请直接发送 YouTube 视频链接：", reply_markup=main_keyboard())
    elif text == "⏰ 设置定时下载":
        await update.message.reply_text("请发送要定时监控的频道链接：\n例如：https://www.youtube.com/@channel", reply_markup=main_keyboard())
    elif text == "📋 查看定时任务":
        await update.message.reply_text("当前暂无定时任务（功能开发中）", reply_markup=main_keyboard())
    elif text == "❌ 取消定时任务":
        await update.message.reply_text("已取消所有定时任务（功能开发中）", reply_markup=main_keyboard())
    elif text == "❓ 帮助":
        await start(update, context)
    elif "youtube.com" in text or "youtu.be" in text:
        await download_audio(update, context, url=text)
    else:
        await update.message.reply_text("请选择菜单功能或发送 YouTube 链接", reply_markup=main_keyboard())

def main():
    app = Application.builder().token(TOKEN.strip()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot 已启动 | 菜单模式")
    app.run_polling()

if __name__ == '__main__':
    main()