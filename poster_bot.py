import os
import logging
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
    Dispatcher,
)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# --- CONFIGURATION (from Environment Variables) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BLOG_ID = os.environ.get("BLOG_ID")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

def send_log(message: str):
    """Sends a message to the log channel if it's configured."""
    if LOG_CHANNEL_ID:
        try:
            bot.send_message(chat_id=LOG_CHANNEL_ID, text=message)
        except Exception as e:
            logger.error(f"Failed to send log message: {e}")

def get_blogger_service():
    """Builds the Blogger service object from environment variables."""
    try:
        creds = Credentials(
            token=None,  # No access token needed, it will be refreshed
            refresh_token=GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=['https://www.googleapis.com/auth/blogger']
        )
        service = build('blogger', 'v3', credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to build Google service: {e}")
        return None

# --- BOT HANDLERS ---
GET_TITLE, GET_PHOTO, GET_CAPTION = range(3)

def start(update: Update, context: CallbackContext) -> int:
    send_log(f"ℹ️ New conversation started by {update.effective_user.first_name}.")
    update.message.reply_text("Hi! Let's create a new blog post. What is the title?\nSend /cancel to stop.")
    return GET_TITLE

def get_title(update: Update, context: CallbackContext) -> int:
    context.user_data['title'] = update.message.text
    update.message.reply_text(f"Title: '{context.user_data['title']}'.\nNow, send the photo.")
    return GET_PHOTO

def get_photo(update: Update, context: CallbackContext) -> int:
    photo_file = update.message.photo[-1].get_file()
    photo_path = f"{photo_file.file_id}.jpg"
    photo_file.download(photo_path)
    context.user_data['photo_path'] = photo_path
    update.message.reply_text("Photo received. Now, what's the caption? You can include links.")
    return GET_CAPTION

def get_caption(update: Update, context: CallbackContext) -> int:
    context.user_data['caption'] = update.message.text
    title = context.user_data['title']
    update.message.reply_text(f"Got it! Publishing '{title}' to your blog...")
    try:
        service = get_blogger_service()
        if not service:
            update.message.reply_text("Error: Could not connect to Google. Please check server logs.")
            send_log("❌ FATAL ERROR! Could not build Google Blogger service. Check credentials.")
            return ConversationHandler.END

        caption = context.user_data['caption']
        photo_path = context.user_data['photo_path']
        body_html = f"<p>{caption.replace(os.linesep, '<br>')}</p>"
        body = {"kind": "blogger#post", "blog": {"id": BLOG_ID}, "title": title, "content": body_html}
        posts = service.posts()
        posts.insert(blogId=BLOG_ID, body=body, isDraft=False).execute()
        update.message.reply_text(f"Success! Post '{title}' published.")
        send_log(f"✅ Success! Post '{title}' published by {update.effective_user.first_name}.")
        os.remove(photo_path)
    except Exception as e:
        update.message.reply_text(f"An error occurred: {e}")
        logger.error(f"Error during posting: {e}")
        send_log(f"❌ ERROR! Failed to post '{title}'.\nError: {e}")
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext) -> int:
    send_log(f"ℹ️ Conversation cancelled by {update.effective_user.first_name}.")
    update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# --- FLASK WEB SERVER SETUP ---
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, use_context=True)

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        GET_TITLE: [MessageHandler(Filters.text & ~Filters.command, get_title)],
        GET_PHOTO: [MessageHandler(Filters.photo, get_photo)],
        GET_CAPTION: [MessageHandler(Filters.text & ~Filters.command, get_caption)],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    persistent=True, name="blogger_conversation"
)
dispatcher.add_handler(conv_handler)

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

@app.route('/')
def index():
    return 'Bot is running!'

if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}")
        logger.info(f"Webhook set to {WEBHOOK_URL}")
        send_log("🚀 Bot has been deployed/restarted!")
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)