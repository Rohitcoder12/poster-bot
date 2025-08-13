import os
import pickle
import base64
import logging
from flask import Flask, request # Import Flask
from telegram import Update, Bot
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
    Dispatcher,
)
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- CONFIGURATION (from Environment Variables) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BLOG_ID = os.environ.get("BLOG_ID")
GOOGLE_CREDS_STRING = os.environ.get("GOOGLE_CREDS_STRING")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") # The public URL of our web service

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Define conversation states
GET_TITLE, GET_PHOTO, GET_CAPTION = range(3)

# --- GOOGLE AUTH FUNCTION (This remains the same) ---
def get_blogger_service():
    creds = None
    if GOOGLE_CREDS_STRING:
        creds_decoded = base64.b64decode(GOOGLE_CREDS_STRING)
        creds = pickle.loads(creds_decoded)
    # The local setup logic is kept for generating the initial string
    elif os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', ['https://www.googleapis.com/auth/blogger'])
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
        creds_encoded = base64.b64encode(pickle.dumps(creds)).decode('utf-8')
        print("--- COPY YOUR GOOGLE CREDENTIALS STRING BELOW ---\n")
        print(creds_encoded)
        print("\n--- END OF STRING ---")
    return build('blogger', 'v3', credentials=creds)

# --- BOT HANDLERS (These remain the same) ---
def start(update: Update, context: CallbackContext) -> int:
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
    update.message.reply_text("Got it! Publishing to your blog...")
    try:
        service = get_blogger_service()
        title = context.user_data['title']
        caption = context.user_data['caption']
        photo_path = context.user_data['photo_path']
        body_html = f"<p>{caption.replace(os.linesep, '<br>')}</p>"
        body = {"kind": "blogger#post", "blog": {"id": BLOG_ID}, "title": title, "content": body_html}
        posts = service.posts()
        posts.insert(blogId=BLOG_ID, body=body, isDraft=False).execute()
        update.message.reply_text(f"Success! Post '{title}' published.", reply_markup=ReplyKeyboardRemove())
        os.remove(photo_path)
    except Exception as e:
        update.message.reply_text(f"An error occurred: {e}")
        logger.error(f"Error during posting: {e}")
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- FLASK WEB SERVER SETUP ---
app = Flask(__name__)
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

# Define the conversation handler
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        GET_TITLE: [MessageHandler(Filters.text & ~Filters.command, get_title)],
        GET_PHOTO: [MessageHandler(Filters.photo, get_photo)],
        GET_CAPTION: [MessageHandler(Filters.text & ~Filters.command, get_caption)],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    # Use persistence in memory for webhooks
    persistent=True,
    name="blogger_conversation"
)
dispatcher.add_handler(conv_handler)

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    """This function handles the incoming updates from Telegram."""
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

@app.route('/')
def index():
    """A simple route to check if the bot is running."""
    return 'Bot is running!'

# This part is for setting the webhook and running the Flask app
if __name__ == "__main__":
    # Check for required environment variables
    if not all([TELEGRAM_TOKEN, BLOG_ID]):
        logger.error("ERROR: TELEGRAM_TOKEN and BLOG_ID environment variables must be set.")
    elif not GOOGLE_CREDS_STRING and not os.path.exists('credentials.json'):
         logger.error("ERROR: GOOGLE_CREDS_STRING must be set for cloud, or credentials.json must exist for local setup.")
    else:
        # Set the webhook only when running on a server (when WEBHOOK_URL is set)
        if WEBHOOK_URL:
            # We set the webhook URL to be our server's address plus the bot token for a secret path
            bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}")
            logger.info(f"Webhook set to {WEBHOOK_URL}")

        # Get port from environment variable or default to 8000
        port = int(os.environ.get('PORT', 8000))
        app.run(host='0.0.0.0', port=port)