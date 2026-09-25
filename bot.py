import os
import asyncio
from aiohttp import web
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

system_instruction = """
Aap ek helpful, smart aur friendly personal AI assistant hain.
Aap user se saral Hindi/Hinglish me aadar ke sath baat karte hain.
Planning, general Q&A, coding, aur Instagram video/audio/reel analysis sabhi me vistrit help karte hain.
"""

# Dono models initialize karein
pro_model = genai.GenerativeModel("gemini-2.5-pro", system_instruction=system_instruction)
flash_model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_instruction)

user_chats = {}
user_modes = {}  # Har user ka active model ('pro' ya 'flash')

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
        "✨ **Active Model:** Gemini 2.5 Pro (Advanced)\n"
        "💡 *Note:* Agar Pro model ki daily limit poori ho jayegi, toh main aapko bata kar automatically Flash model par shift ho jaunga.\n\n"
        "• Nayi planning ya chat ke liye: /clear\n"
        "• Model check ya badalne ke liye: /mode"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_modes.get(user_id, "pro")
    active_model = pro_model if mode == "pro" else flash_model
    user_chats[user_id] = active_model.start_chat(history=[])
    await update.message.reply_text(f"Chat memory reset ho gayi hai! (Current Mode: {mode.upper()})")

# Model check ya change karne ka command
async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_mode = user_modes.get(user_id, "pro")

    if context.args:
        choice = context.args[0].lower()
        if choice in ["pro", "flash"]:
            user_modes[user_id] = choice
            active_model = pro_model if choice == "pro" else flash_model
            user_chats[user_id] = active_model.start_chat(history=[])
            await update.message.reply_text(f"Model successfully badal kar **Gemini {choice.upper()}** kar diya gaya hai!", parse_mode="Markdown")
            return

    await update.message.reply_text(
        f"Abhi active model: **Gemini {current_mode.upper()}** hai.\n\n"
        "Badalne ke liye likhein:\n"
        "• `/mode pro` - Advanced Pro model ke liye\n"
        "• `/mode flash` - Unlimited Fast model ke liye",
        parse_mode="Markdown"
    )

# Text Messages + Auto Fallback Logic
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    chat_session, mode = get_chat_session(user_id)

    status_msg = await update.message.reply_text("Soch raha hoon...")

    try:
        response = await asyncio.to_thread(chat_session.send_message, user_text)
        reply = response.text if response.text else "Jawab generate nahi ho saka."
        await status_msg.edit_text(reply)

    except Exception as e:
        err_str = str(e)
        # Agar Pro model ki limit (429 Quota Exhausted) aa jaye
        if "429" in err_str or "quota" in err_str.lower() or "resourceexhausted" in err_str.lower():
            user_modes[user_id] = "flash"
            # Flash chat session shuru karein
            flash_chat = flash_model.start_chat(history=[])
            user_chats[user_id] = flash_chat
            
            warning = (
                "⚠️ **Gemini Pro (Advanced) ki daily limit poori ho gayi hai!**\n"
                "Chat bina ruke chalti rahe, isliye maine automatically **Gemini Flash** par shift kar diya hai.\n\n"
                "Aapke sawal ka jawab Flash se taiyar hai:\n\n"
            )
            try:
                flash_res = await asyncio.to_thread(flash_chat.send_message, user_text)
                reply = warning + (flash_res.text if flash_res.text else "Jawab generate nahi ho saka.")
            except Exception as flash_err:
                reply = f"Error in Flash: {str(flash_err)}"

            await status_msg.edit_text(reply, parse_mode="Markdown")
        else:
            await status_msg.edit_text(f"Error: {err_str}")

# Video Analysis + Fallback
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_modes.get(user_id, "pro")
    active_model = pro_model if mode == "pro" else flash_model

    caption = update.message.caption or "Is video aur audio ko analyze karke poori jankari do."
    status_msg = await update.message.reply_text("Video download karke analyze ho raha hai...")

    temp_video_path = f"temp_{update.message.message_id}.mp4"
    try:
        video_obj = update.message.video or update.message.animation or update.message.document
        file = await context.bot.get_file(video_obj.file_id)
        await file.download_to_drive(temp_video_path)

        uploaded_file = await asyncio.to_thread(genai.upload_file, temp_video_path)
        while uploaded_file.state.name == "PROCESSING":
            await asyncio.sleep(2)
            uploaded_file = await asyncio.to_thread(genai.get_file, uploaded_file.name)

        prompt = f"Video aur audio ko dekh/sun kar jawab dein: {caption}"
        try:
            response = await asyncio.to_thread(active_model.generate_content, [uploaded_file, prompt])
            reply = response.text if response.text else "Video analyze nahi ho saka."
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                user_modes[user_id] = "flash"
                flash_res = await asyncio.to_thread(flash_model.generate_content, [uploaded_file, prompt])
                reply = "⚠️ Pro limit poori hone par Flash model se analysis:\n\n" + (flash_res.text if flash_res.text else "")
            else:
                reply = f"Error: {str(e)}"

    except Exception as e:
        reply = f"Error: {str(e)}"
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)

    await status_msg.edit_text(reply)

async def health_check(request):
    return web.Response(text="Bot is running 24/7!")

async def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        print("Keys missing!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("mode", mode_command))
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
