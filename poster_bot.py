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

# --- NEW: Add your permanent links here ---
TELEGRAM_CHANNEL_LINK = os.environ.get("TELEGRAM_CHANNEL_LINK")
INSTAGRAM_LINK = os.environ.get("INSTAGRAM_LINK")


# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

# --- HELPER FUNCTIONS ---
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

# --- BOT HANDLERS (NEW CONVERSATION FLOW) ---
# --- NEW STATES: Added GET_PHOTO and GET_LINKS ---
GET_TITLE, GET_PHOTO, GET_CAPTION, GET_LINKS = range(4)

def start(update: Update, context: CallbackContext) -> int:
    send_log(f"ℹ️ New conversation started by {update.effective_user.first_name}.")
    update.message.reply_text("Hi! Let's create a new post.\n\nFirst, what is the title?")
    return GET_TITLE

def get_title(update: Update, context: CallbackContext) -> int:
    context.user_data['title'] = update.message.text
    update.message.reply_text(f"Great! Title is set.\n\nNow, please send the photo for the post.")
    return GET_PHOTO

def get_photo(update: Update, context: CallbackContext) -> int:
    photo_file = update.message.photo[-1].get_file()
    photo_path = f"{photo_file.file_id}.jpg"
    photo_file.download(photo_path)
    context.user_data['photo_path'] = photo_path
    update.message.reply_text("Photo received.\n\nNext, send the caption (the text description).")
    return GET_CAPTION

def get_caption(update: Update, context: CallbackContext) -> int:
    context.user_data['caption'] = update.message.text
    update.message.reply_text("Caption saved.\n\nFinally, send the video link(s). You can send one or multiple links in one message.")
    return GET_LINKS

# --- This is the FINAL function that builds and creates the post ---
def create_post(update: Update, context: CallbackContext) -> int:
    links_text = update.message.text
    title = context.user_data.get('title', 'No Title')
    
    update.message.reply_text(f"Got it! Publishing '{title}' to your blog...")
    
    try:
        service = get_blogger_service()
        if not service:
            update.message.reply_text("Error: Could not connect to Google.")
            send_log("❌ FATAL ERROR! Could not build Google Blogger service.")
            return ConversationHandler.END

        caption_text = context.user_data.get('caption', '')
        photo_path = context.user_data.get('photo_path')

        # --- DYNAMIC LINK & BUTTON CREATION ---
        # Find all URLs in the links message
        urls = re.findall(r'https?://\S+', links_text)
        
        dynamic_buttons_html = ""
        if len(urls) == 1:
            # If there's only one link, label it "Video"
            dynamic_buttons_html = f'<a href="{urls[0]}" class="video-button" target="_blank">🎬 Watch Video</a>'
        elif len(urls) > 1:
            # If multiple links, label them "Video 1", "Video 2", etc.
            for i, url in enumerate(urls):
                dynamic_buttons_html += f'<a href="{url}" class="video-button" target="_blank">🎬 Watch Video {i + 1}</a>'

        # --- STATIC FOOTER BUTTON CREATION ---
        footer_buttons_html = ""
        if TELEGRAM_CHANNEL_LINK:
            footer_buttons_html += f'<a href="{TELEGRAM_CHANNEL_LINK}" class="social-button telegram" target="_blank">Join All Channels</a>'
        if INSTAGRAM_LINK:
            footer_buttons_html += f'<a href="{INSTAGRAM_LINK}" class="social-button instagram" target="_blank">Follow on Instagram</a>'

        # --- UPLOAD IMAGE AND BUILD FINAL HTML ---
        image_url = upload_to_imagebb(photo_path)
        
        # Define CSS styles for the post and buttons
        style_block = """
        <style>
            .post-container { text-align: center; font-family: sans-serif; }
            .post-container img { max-width: 100%; height: auto; border-radius: 12px; margin-bottom: 20px; }
            .post-caption { font-size: 1.1em; color: #444; line-height: 1.6; padding: 0 10px; margin-bottom: 25px; }
            .button-container { margin-bottom: 30px; }
            .video-button, .social-button {
                display: inline-block; padding: 12px 28px; margin: 8px; font-size: 16px; font-weight: bold; color: #ffffff;
                border: none; border-radius: 8px; text-decoration: none; transition: transform 0.2s;
            }
            .video-button:hover, .social-button:hover { transform: scale(1.05); }
            .video-button { background-color: #ff4500; } /* OrangeRed */
            .social-button.telegram { background-color: #0088cc; } /* Telegram Blue */
            .social-button.instagram { background: #d6249f; background: radial-gradient(circle at 30% 107%, #fdf497 0%, #fdf497 5%, #fd5949 45%,#d6249f 60%,#285AEB 90%); }
        </style>
        """

        body_html = f"""
        {style_block}
        <div class="post-container">
            <img src="{image_url if image_url else ''}" />
            <div class="post-caption">{caption_text.replace(os.linesep, "<br>")}</div>
            <div class="button-container">{dynamic_buttons_html}</div>
            <div class="footer-container">{footer_buttons_html}</div>
        </div>
        """
        
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
# The dispatcher needs to be configured with the new states
dispatcher = Dispatcher(bot, None, use_context=True)

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        GET_TITLE: [MessageHandler(Filters.text & ~Filters.command, get_title)],
        GET_PHOTO: [MessageHandler(Filters.photo, get_photo)],
        GET_CAPTION: [MessageHandler(Filters.text & ~Filters.command, get_caption)],
        GET_LINKS: [MessageHandler(Filters.text & ~Filters.command, create_post)],
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