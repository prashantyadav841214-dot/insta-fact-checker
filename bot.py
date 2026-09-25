import os
import re
import glob
import asyncio
from aiohttp import web
import yt_dlp
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

system_instruction = """
Aap ek helpful personal AI assistant hain jo saral Hindi/Hinglish me baat karte hain.
Jab user koi Instagram video ya reel bheje, toh video me likhe hue text, scenes, background audio aur context ko vistar se samjhayein.
"""

# Latest Gemini 3 series models
pro_model = genai.GenerativeModel("gemini-3.1-pro-preview", system_instruction=system_instruction)
flash_model = genai.GenerativeModel("gemini-3-flash-preview", system_instruction=system_instruction)

user_chats = {}
user_modes = {}

def get_chat_session(user_id):
    mode = user_modes.get(user_id, "pro")
    if user_id not in user_chats:
        active_model = pro_model if mode == "pro" else flash_model
        user_chats[user_id] = active_model.start_chat(history=[])
    return user_chats[user_id], mode

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_modes[user_id] = "pro"
    user_chats[user_id] = pro_model.start_chat(history=[])
    welcome_text = (
        "Namaste! Main aapka personal Gemini AI Assistant hoon.\n\n"
        "Ab aap Instagram Reel ka **Link** bhej sakte hain ya seedhe **Video** bhej sakte hain. "
        "Main khud analyze karke aapko bataunga!"
    )
    await update.message.reply_text(welcome_text)

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_modes.get(user_id, "pro")
    active_model = pro_model if mode == "pro" else flash_model
    user_chats[user_id] = active_model.start_chat(history=[])
    await update.message.reply_text("Chat memory reset ho gayi hai!")

# Instagram download function
def download_insta(url, prefix):
    ydl_opts = {
        'outtmpl': f'{prefix}.%(ext)s',
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    files = glob.glob(f"{prefix}*")
    return files[0] if files else None

# Text ya Link message aane par
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    chat_session, mode = get_chat_session(user_id)
    active_model = pro_model if mode == "pro" else flash_model

    # Check karein agar message me Instagram link hai
    insta_match = re.search(r'(https?://[^\s]*instagram\.com/[^\s]+)', user_text)

    if insta_match:
        insta_url = insta_match.group(1)
        status_msg = await update.message.reply_text("Instagram Reel link mila! Background me download kiya ja raha hai...")
        prefix = f"insta_{user_id}_{update.message.message_id}"
        video_path = None

        try:
            video_path = await asyncio.to_thread(download_insta, insta_url, prefix)

            if video_path and os.path.exists(video_path):
                await status_msg.edit_text("Video download ho gaya! Ab Gemini se analyze karwaya ja raha hai...")
                uploaded_file = await asyncio.to_thread(genai.upload_file, video_path)

                while uploaded_file.state.name == "PROCESSING":
                    await asyncio.sleep(2)
                    uploaded_file = await asyncio.to_thread(genai.get_file, uploaded_file.name)

                prompt = (
                    f"Aap is Instagram Reel video aur audio ko dhyan se dekhein aur sunein.\n"
                    f"User ka nirdesh: '{user_text}'.\n\n"
                    f"Kripya saral Hindi me vistar se batayein:\n"
                    f"1. Is video me kya text/baatein likhi hain?\n"
                    f"2. Video me kya dikhaya aur bola gaya hai?\n"
                    f"3. Audio/song kya hai aur iska context kya hai?"
                )
                try:
                    res = await asyncio.to_thread(active_model.generate_content, [uploaded_file, prompt])
                    reply = res.text if res.text else "Analysis generate nahi ho saka."
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower():
                        res = await asyncio.to_thread(flash_model.generate_content, [uploaded_file, prompt])
                        reply = "⚠️ Pro limit poori hone par Flash se analysis:\n\n" + (res.text if res.text else "")
                    else:
                        reply = f"Gemini Error: {str(e)}"

                await status_msg.edit_text(reply)
            else:
                await status_msg.edit_text(
                    "Instagram ne is video ko direct download hone se rok diya hai.\n"
                    "💡 Kripya reel ka video save karke seedhe Telegram par bhej dein, main turant dekh kar bata dunga!"
                )
        except Exception:
            await status_msg.edit_text(
                "Instagram security ki wajah se link se video download nahi ho saka.\n"
                "💡 Aap reel ko download karke Telegram me video bhej dijiye, bot turant padh lega!"
            )
        finally:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
            for f in glob.glob(f"{prefix}*"):
                try:
                    os.remove(f)
                except Exception:
                    pass
        return

    # Normal Chat / Planning
    status_msg = await update.message.reply_text("Soch raha hoon...")
    try:
        response = await asyncio.to_thread(chat_session.send_message, user_text)
        reply = response.text if response.text else "Jawab generate nahi ho saka."
        await status_msg.edit_text(reply)
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            user_modes[user_id] = "flash"
            flash_chat = flash_model.start_chat(history=[])
            user_chats[user_id] = flash_chat
            flash_res = await asyncio.to_thread(flash_chat.send_message, user_text)
            reply = "⚠️ Pro limit poori hone par Flash se jawab:\n\n" + (flash_res.text if flash_res.text else "")
            await status_msg.edit_text(reply)
        else:
            await status_msg.edit_text(f"Error: {str(e)}")

# Direct Video aane par
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_modes.get(user_id, "pro")
    active_model = pro_model if mode == "pro" else flash_model

    caption = update.message.caption or "Is video me jo likha aur bola gaya hai, Hindi me poori jankari do."
    status_msg = await update.message.reply_text("Video analyze ho raha hai...")

    temp_video_path = f"temp_{update.message.message_id}.mp4"
    try:
        video_obj = update.message.video or update.message.animation or update.message.document
        file = await context.bot.get_file(video_obj.file_id)
        await file.download_to_drive(temp_video_path)

        uploaded_file = await asyncio.to_thread(genai.upload_file, temp_video_path)
        while uploaded_file.state.name == "PROCESSING":
            await asyncio.sleep(2)
            uploaded_file = await asyncio.to_thread(genai.get_file, uploaded_file.name)

        prompt = f"Video aur audio ko dekh/sun kar saral Hindi me vistar se samjhayein: {caption}"
        try:
            response = await asyncio.to_thread(active_model.generate_content, [uploaded_file, prompt])
            reply = response.text if response.text else "Video analyze nahi ho saka."
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                user_modes[user_id] = "flash"
                flash_res = await asyncio.to_thread(flash_model.generate_content, [uploaded_file, prompt])
                reply = "⚠️ Pro limit poori hone par Flash se analysis:\n\n" + (flash_res.text if flash_res.text else "")
            else:
                reply = f"Error: {str(e)}"

    except Exception as e:
        reply = f"Error: {str(e)}"
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)

    await status_msg.edit_text(reply)

# Render health check
async def health_check(request):
    return web.Response(text="Bot is running 24/7!")

async def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        print("Keys missing!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.VIDEO | filters.ANIMATION | filters.Document.VIDEO, handle_video))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"Bot running on port {port}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
