import os
import asyncio
from aiohttp import web
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Keys Render ke Environment Variables se aayengi (Secure)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Gemini setup with System Instructions
genai.configure(api_key=GEMINI_API_KEY)

system_instruction = """
Aap ek helpful, smart aur friendly personal AI assistant hain (theek Gemini ki tarah).
Aap user se saral Hindi/Hinglish me aadar ke sath baat karte hain.
Aap ye sabhi kaam kar sakte hain:
1. Planning: Study plan, work schedule, daily planning, ideas brainstorming.
2. Q&A: Science, history, technology, coding ya aam sawalon ke sahi jawab dena.
3. Instagram/Video Analysis: Video ke visual scenes, background music/songs, fact-check aur explanations batana.
User ke sath lamba context yaad rakhkar natural aur helpful dhang se baat karein.
"""

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=system_instruction
)

# Har user ki chat memory store karne ke liye
user_chats = {}

def get_user_chat(user_id):
    if user_id not in user_chats:
        user_chats[user_id] = model.start_chat(history=[])
    return user_chats[user_id]

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_chats[user_id] = model.start_chat(history=[])
    welcome_text = (
        "Namaste! Main aapka personal Gemini AI Assistant hoon.\n\n"
        "Aap mujhse:\n"
        "• Kisi bhi cheez ki planning ya brainstorming karwa sakte hain.\n"
        "• Koi bhi general sawal ya technical doubt puch sakte hain.\n"
        "• Instagram reel ka link ya video bhej kar uske baare me kuch bhi jaan sakte hain.\n\n"
        "Nayi baat ya planning shuru karne ke liye kabhi bhi /clear bhej sakte hain."
    )
    await update.message.reply_text(welcome_text)

# /clear command (Memory reset)
async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_chats[user_id] = model.start_chat(history=[])
    await update.message.reply_text("Chat memory reset ho gayi hai. Ab naye topic par baat shuru kar sakte hain!")

# Text messages (Chat, planning, questions)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    chat_session = get_user_chat(user_id)

    status_msg = await update.message.reply_text("Soch raha hoon...")

    try:
        response = await asyncio.to_thread(chat_session.send_message, user_text)
        reply = response.text if response.text else "Jawab generate nahi ho saka."
    except Exception as e:
        reply = f"Error: {str(e)}"

    await status_msg.edit_text(reply)

# Video analysis
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.caption or "Is video aur audio ko analyze karke poori jankari do."
    status_msg = await update.message.reply_text("Video aur audio analyze kiya ja raha hai, kripya thoda intezar karein...")

    temp_video_path = f"temp_{update.message.message_id}.mp4"
    try:
        video_obj = update.message.video or update.message.animation or update.message.document
        file = await context.bot.get_file(video_obj.file_id)
        await file.download_to_drive(temp_video_path)

        uploaded_file = await asyncio.to_thread(genai.upload_file, temp_video_path)

        while uploaded_file.state.name == "PROCESSING":
            await asyncio.sleep(2)
            uploaded_file = await asyncio.to_thread(genai.get_file, uploaded_file.name)

        prompt = f"Video aur audio ko dhyan se dekh/sun kar user ke is sawal ka vistar se jawab dein: {caption}"
        response = await asyncio.to_thread(model.generate_content, [uploaded_file, prompt])
        reply = response.text if response.text else "Video analyze nahi ho saka."

    except Exception as e:
        reply = f"Error: {str(e)}"
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)

    await status_msg.edit_text(reply)

# Render 24/7 web server
async def health_check(request):
    return web.Response(text="Bot is running 24/7!")

async def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        print("Error: Keys missing! Please set TELEGRAM_BOT_TOKEN and GEMINI_API_KEY in Render.")
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
