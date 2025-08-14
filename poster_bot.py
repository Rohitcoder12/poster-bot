import os
import logging
import requests
import re
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
IMAGEBB_API_KEY = os.environ.get("IMAGEBB_API_KEY")

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

# --- HELPER FUNCTIONS (No changes here) ---
def send_log(message: str):
    if LOG_CHANNEL_ID:
        try: bot.send_message(chat_id=LOG_CHANNEL_ID, text=message)
        except Exception as e: logger.error(f"Failed to send log message: {e}")

def get_blogger_service():
    try:
        creds = Credentials(
            token=None, refresh_token=GOOGLE_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET, scopes=['https://www.googleapis.com/auth/blogger']
        )
        service = build('blogger', 'v3', credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to build Google service: {e}")
        return None

def upload_to_imagebb(image_path):
    if not IMAGEBB_API_KEY:
        logger.warning("IMAGEBB_API_KEY not set. Cannot upload image.")
        return None
    upload_url = "https://api.imgbb.com/1/upload"
    with open(image_path, "rb") as image_file:
        payload = {"key": IMAGEBB_API_KEY}
        files = {"image": image_file}
        try:
            response = requests.post(upload_url, params=payload, files=files)
            response.raise_for_status()
            json_response = response.json()
            if json_response.get("success"):
                return json_response["data"]["url"]
        except requests.RequestException as e:
            logger.error(f"ImageBB upload failed: {e}")
            return None
    return None

# --- BOT HANDLERS (No changes here, except get_caption) ---
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
            update.message.reply_text("Error: Could not connect to Google.")
            send_log("❌ FATAL ERROR! Could not build Google Blogger service.")
            return ConversationHandler.END

        caption_text = context.user_data['caption']
        photo_path = context.user_data['photo_path']

        # --- FINAL UPGRADE: Build beautiful HTML with styled buttons ---
        
        # This function finds links and turns them into styled buttons
        def create_styled_buttons(text):
            # This regex finds http/https links
            url_pattern = re.compile(r'(https?://\S+)')
            # Replace found URLs with the button HTML
            return url_pattern.sub(r'<a href="\1" class="download-button" target="_blank">Download Now</a>', text)

        # Process the caption text
        caption_with_buttons = create_styled_buttons(caption_text)
        final_caption_html = caption_with_buttons.replace(os.linesep, "<br>")

        # Upload the image
        image_url = upload_to_imagebb(photo_path)
        
        # Define CSS styles for the post and buttons
        style_block = """
        <style>
            .post-container {
                text-align: center;
                font-family: Arial, sans-serif;
            }
            .post-container img {
                max-width: 100%;
                height: auto;
                border-radius: 8px;
                margin-bottom: 15px;
            }
            .post-caption {
                font-size: 16px;
                color: #333;
                line-height: 1.6;
                padding: 0 10px;
            }
            .download-button {
                display: inline-block;
                padding: 12px 25px;
                margin: 10px 5px;
                font-size: 16px;
                font-weight: bold;
                color: #ffffff;
                background-color: #007bff;
                border: none;
                border-radius: 5px;
                text-decoration: none;
                transition: background-color 0.3s;
            }
            .download-button:hover {
                background-color: #0056b3;
            }
        </style>
        """

        if image_url:
            body_html = f"""
            {style_block}
            <div class="post-container">
                <img src="{image_url}" />
                <div class="post-caption">
                    {final_caption_html}
                </div>
            </div>
            """
            send_log(f"📸 Image successfully uploaded to ImageBB: {image_url}")
        else:
            # Fallback if image upload fails
            body_html = f"""
            {style_block}
            <div class="post-container">
                <div class="post-caption">
                    {final_caption_html}
                </div>
            </div>
            """
            send_log(f"⚠️ ImageBB upload failed. Posting text only.")
        
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

# --- FLASK WEB SERVER SETUP (No changes from here down) ---
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
    name="blogger_conversation"
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