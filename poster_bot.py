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
TELEGRAM_CHANNEL_LINK = os.environ.get("TELEGRAM_CHANNEL_LINK")
INSTAGRAM_LINK = os.environ.get("INSTAGRAM_LINK")
SOURCE_CHANNEL_IDS_STR = os.environ.get("SOURCE_CHANNEL_IDS", "")
SOURCE_CHANNEL_IDS = [int(channel_id.strip()) for channel_id in SOURCE_CHANNEL_IDS_STR.split(',') if channel_id.strip()]

# --- NEW: Domain Management ---
DOMAINS_FILE = "allowed_domains.txt"
DEFAULT_DOMAINS_STR = "tinyurl.com,terabox.com,mirrobox.com,nephobox.com,freeterabox.com,1024tera.com,4funbox.co,terabox.app,momerybox.com,teraboxapp.com,tibibox.com,terasharelink.com,teraboxurl.com"

# --- NEW: Functions to load and save domains ---
def load_domains():
    if os.path.exists(DOMAINS_FILE):
        with open(DOMAINS_FILE, "r") as f:
            return {line.strip() for line in f if line.strip()}
    else:
        default_domains = {domain.strip() for domain in DEFAULT_DOMAINS_STR.split(',') if domain.strip()}
        save_domains(default_domains)
        return default_domains

def save_domains(domains_set):
    with open(DOMAINS_FILE, "w") as f:
        for domain in sorted(list(domains_set)):
            f.write(f"{domain}\n")

# Load domains on startup
VALID_LINK_DOMAINS = load_domains()


# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

# --- HELPER FUNCTIONS (Original Code) ---
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
        return None
    upload_url = "https://api.imgbb.com/1/upload"
    with open(image_path, "rb") as image_file:
        payload = {"key": IMAGEBB_API_KEY}
        files = {"image": image_file}
        try:
            response = requests.post(upload_url, params=payload, files=files)
            response.raise_for_status()
            json_response = response.json()
            return json_response["data"]["url"] if json_response.get("success") else None
        except requests.RequestException as e:
            logger.error(f"ImageBB upload failed: {e}")
            return None

def build_blog_post_html(image_url, caption_text, links_list):
    dynamic_buttons_html = ""
    if len(links_list) == 1:
        dynamic_buttons_html = f'<a href="{links_list[0]}" class="video-button" target="_blank">🎬 Watch Video</a>'
    elif len(links_list) > 1:
        for i, url in enumerate(links_list):
            dynamic_buttons_html += f'<a href="{url}" class="video-button" target="_blank">🎬 Watch Video {i + 1}</a>'
    footer_buttons_html = ""
    if TELEGRAM_CHANNEL_LINK:
        footer_buttons_html += f'<a href="{TELEGRAM_CHANNEL_LINK}" class="social-button telegram" target="_blank">Join All Channels</a>'
    if INSTAGRAM_LINK:
        footer_buttons_html += f'<a href="{INSTAGRAM_LINK}" class="social-button instagram" target="_blank">Follow on Instagram</a>'
    style_block = """<style>.post-container{text-align:center;font-family:sans-serif}.post-container img{max-width:100%;height:auto;border-radius:12px;margin-bottom:20px}.post-caption{font-size:1.1em;color:#444;line-height:1.6;padding:0 10px;margin-bottom:25px}.button-container{margin-bottom:30px}.video-button,.social-button{display:inline-block;padding:12px 28px;margin:8px;font-size:16px;font-weight:bold;color:#fff;border:none;border-radius:8px;text-decoration:none;transition:transform .2s}.video-button:hover,.social-button:hover{transform:scale(1.05)}.video-button{background-color:#ff4500}.social-button.telegram{background-color:#0088cc}.social-button.instagram{background:#d6249f;background:radial-gradient(circle at 30% 107%,#fdf497 0,#fdf497 5%,#fd5949 45%,#d6249f 60%,#285aeb 90%)}</style>"""
    return f"""{style_block}<div class="post-container"><img src="{image_url if image_url else ''}" /><div class="post-caption">{caption_text.replace(os.linesep, "<br>")}</div><div class="button-container">{dynamic_buttons_html}</div><div class="footer-container">{footer_buttons_html}</div></div>"""

def process_and_publish_post(context: CallbackContext, title: str, caption_text: str, photo_path: str, links_list: list, user_name: str, source: str):
    try:
        service = get_blogger_service()
        if not service:
            send_log(f"❌ {source.upper()} ERROR! Could not build Google Blogger service.")
            if source == 'manual': context.bot.send_message(chat_id=context.user_data['chat_id'], text="Error: Could not connect to Google.")
            return
        image_url = upload_to_imagebb(photo_path)
        body_html = build_blog_post_html(image_url, caption_text, links_list)
        body = {"kind": "blogger#post", "blog": {"id": BLOG_ID}, "title": title, "content": body_html}
        posts = service.posts()
        posts.insert(blogId=BLOG_ID, body=body, isDraft=False).execute()
        send_log(f"✅ {source.upper()} SUCCESS! Post '{title}' published by {user_name}.")
        if source == 'manual': context.bot.send_message(chat_id=context.user_data['chat_id'], text=f"Success! Post '{title}' published.")
    except Exception as e:
        send_log(f"❌ {source.upper()} ERROR! Failed to post '{title}'.\nError: {e}")
        if source == 'manual': context.bot.send_message(chat_id=context.user_data['chat_id'], text=f"An error occurred: {e}")
    finally:
        if os.path.exists(photo_path):
            os.remove(photo_path)

# --- AUTOMATED CHANNEL POST HANDLER (Original logic, with new domain checker) ---
def channel_post_handler(update: Update, context: CallbackContext):
    post = update.channel_post
    if post.chat_id not in SOURCE_CHANNEL_IDS or not (post.photo or post.video):
        return
    send_log(f"AUTOMATION: Detected new media in channel {post.chat.title} ({post.chat_id}).")
    if post.video:
        media_file = post.video.thumb.get_file()
    else:
        media_file = post.photo[-1].get_file()
    full_caption = post.caption or ""
    
    # --- MODIFIED: Use the new dynamic domain list instead of hardcoded links ---
    all_urls = re.findall(r'https?://\S+', full_caption)
    valid_urls = [url for url in all_urls if any(domain in url for domain in VALID_LINK_DOMAINS)]
    
    if not valid_urls:
        send_log(f"AUTOMATION: Post ignored. No links found matching the allowed domains: {', '.join(VALID_LINK_DOMAINS)}")
        return

    # --- Original Caption Parsing Logic ---
    stop_keywords = ["Full Video", r"\(BY - @", "👉", "Watch Online", r"https?://"]
    caption_parts = re.split('|'.join(stop_keywords), full_caption, 1, flags=re.IGNORECASE)
    main_caption = caption_parts[0].strip()
    if not main_caption:
        send_log("AUTOMATION: Post ignored. Could not extract a valid caption.")
        return
    title = main_caption.split('\n')[0].strip()
    photo_path = f"temp_{media_file.file_id}.jpg"
    media_file.download(photo_path)
    process_and_publish_post(context, title, main_caption, photo_path, valid_urls, user_name=f"Channel '{post.chat.title}'", source="automation")

# --- MANUAL POSTING BOT HANDLERS (Original Code) ---
GET_TITLE, GET_PHOTO_OR_VIDEO, GET_CAPTION, GET_LINKS = range(4)
def start(update: Update, context: CallbackContext) -> int:
    send_log(f"MANUAL: New conversation started by {update.effective_user.first_name}.")
    update.message.reply_text("Hi! Let's create a post manually.\n\nFirst, what is the title?")
    return GET_TITLE
def get_title(update: Update, context: CallbackContext) -> int:
    context.user_data['title'] = update.message.text
    update.message.reply_text("Title set. Now, please send the photo or video.")
    return GET_PHOTO_OR_VIDEO
def get_photo_or_video(update: Update, context: CallbackContext) -> int:
    if update.message.video:
        media_file = update.message.video.thumb.get_file()
    else:
        media_file = update.message.photo[-1].get_file()
    photo_path = f"temp_{media_file.file_id}.jpg"
    media_file.download(photo_path)
    context.user_data['photo_path'] = photo_path
    context.user_data['chat_id'] = update.effective_chat.id
    update.message.reply_text("Media received. Next, send the caption.")
    return GET_CAPTION
def get_caption(update: Update, context: CallbackContext) -> int:
    context.user_data['caption'] = update.message.text
    update.message.reply_text("Caption saved. Finally, send the video link(s).")
    return GET_LINKS
def create_manual_post(update: Update, context: CallbackContext) -> int:
    links_text = update.message.text
    title = context.user_data.get('title', 'No Title')
    caption_text = context.user_data.get('caption', '')
    photo_path = context.user_data.get('photo_path')
    valid_urls = re.findall(r'https?://\S+', links_text)
    user_name = update.effective_user.first_name
    update.message.reply_text(f"Got it! Publishing '{title}' to your blog...")
    process_and_publish_post(context, title, caption_text, photo_path, valid_urls, user_name, source="manual")
    return ConversationHandler.END
def cancel(update: Update, context: CallbackContext) -> int:
    send_log(f"MANUAL: Conversation cancelled by {update.effective_user.first_name}.")
    update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# --- NEW: Command Handlers for Domain Management ---
def add_site(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Usage: /addsite <domain.com>")
        return
    domain_to_add = context.args[0].lower().strip()
    if domain_to_add in VALID_LINK_DOMAINS:
        update.message.reply_text(f"Domain '{domain_to_add}' is already in the list.")
    else:
        VALID_LINK_DOMAINS.add(domain_to_add)
        save_domains(VALID_LINK_DOMAINS)
        update.message.reply_text(f"Domain '{domain_to_add}' added successfully.")
        send_log(f"ADMIN: Domain added: {domain_to_add} by {update.effective_user.first_name}")

def remove_site(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Usage: /removesite <domain.com>")
        return
    domain_to_remove = context.args[0].lower().strip()
    if domain_to_remove in VALID_LINK_DOMAINS:
        VALID_LINK_DOMAINS.discard(domain_to_remove)
        save_domains(VALID_LINK_DOMAINS)
        update.message.reply_text(f"Domain '{domain_to_remove}' removed successfully.")
        send_log(f"ADMIN: Domain removed: {domain_to_remove} by {update.effective_user.first_name}")
    else:
        update.message.reply_text(f"Domain '{domain_to_remove}' not found in the list.")

def list_sites(update: Update, context: CallbackContext):
    if not VALID_LINK_DOMAINS:
        update.message.reply_text("The list of allowed domains is empty.")
    else:
        message = "<b>Currently Allowed Domains:</b>\n\n"
        message += "\n".join(f"<code>{domain}</code>" for domain in sorted(list(VALID_LINK_DOMAINS)))
        update.message.reply_text(message, parse_mode='HTML')

def help_command(update: Update, context: CallbackContext):
    help_text = """
Hello! Here are the available commands:

/start - Manually create a new post.
/cancel - Stop the manual posting process.
/help - Show this message.

/addsite `<domain.com>` - Add a website to the allowed list.
/removesite `<domain.com>` - Remove a website from the list.
/listsites - Show all allowed websites.
"""
    update.message.reply_text(help_text, parse_mode='Markdown')


# --- FLASK WEB SERVER & DISPATCHER SETUP ---
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, use_context=True)

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        GET_TITLE: [MessageHandler(Filters.text & ~Filters.command, get_title)],
        GET_PHOTO_OR_VIDEO: [MessageHandler(Filters.photo | Filters.video, get_photo_or_video)],
        GET_CAPTION: [MessageHandler(Filters.text & ~Filters.command, get_caption)],
        GET_LINKS: [MessageHandler(Filters.text & ~Filters.command, create_manual_post)],
    },
    fallbacks=[CommandHandler('cancel', cancel)], name="manual_blogger_conversation"
)
dispatcher.add_handler(conv_handler)
dispatcher.add_handler(MessageHandler((Filters.photo | Filters.video) & Filters.chat_type.channel, channel_post_handler))

# --- NEW: Add handlers for new commands ---
dispatcher.add_handler(CommandHandler('addsite', add_site))
dispatcher.add_handler(CommandHandler('removesite', remove_site))
dispatcher.add_handler(CommandHandler('listsites', list_sites))
dispatcher.add_handler(CommandHandler('help', help_command))

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
        send_log("🚀 Bot has been deployed/restarted with dynamic domain features.")
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)