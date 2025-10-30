import os
import sys
import logging
import requests
import re
import traceback
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
ADMIN_ID = os.environ.get("ADMIN_ID")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")
SOURCE_CHANNEL_IDS_STR = os.environ.get("SOURCE_CHANNEL_IDS", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")
IMAGEBB_API_KEY = os.environ.get("IMAGEBB_API_KEY")
TELEGRAM_CHANNEL_LINK = os.environ.get("TELEGRAM_CHANNEL_LINK")
INSTAGRAM_LINK = os.environ.get("INSTAGRAM_LINK")

DEFAULT_DOMAINS_STR = os.environ.get(
    "VALID_LINK_DOMAINS",
    "tinyurl.com,terabox.com,mirrobox.com,nephobox.com,freeterabox.com,1024tera.com,4funbox.co,terabox.app,momerybox.com,teraboxapp.com,tibibox.com,terasharelink.com,teraboxurl.com"
)
DOMAINS_FILE = "allowed_domains.txt"

CRITICAL_VARS = {
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN, "BLOG_ID": BLOG_ID, "ADMIN_ID": ADMIN_ID,
    "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID, "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
    "GOOGLE_REFRESH_TOKEN": GOOGLE_REFRESH_TOKEN
}
missing_vars = [name for name, var in CRITICAL_VARS.items() if not var]
if missing_vars:
    logging.critical(f"FATAL ERROR: Missing critical environment variables: {', '.join(missing_vars)}")
    sys.exit("Exiting due to missing configuration.")

SOURCE_CHANNEL_IDS = [int(channel_id.strip()) for channel_id in SOURCE_CHANNEL_IDS_STR.split(',') if channel_id.strip().isdigit()]

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

def load_domains():
    if os.path.exists(DOMAINS_FILE):
        with open(DOMAINS_FILE, "r") as f:
            return {line.strip() for line in f if line.strip()}
    else:
        logger.info(f"'{DOMAINS_FILE}' not found. Creating it with default domains.")
        default_domains = {domain.strip() for domain in DEFAULT_DOMAINS_STR.split(',') if domain.strip()}
        save_domains(default_domains)
        return default_domains

def save_domains(domains_set):
    with open(DOMAINS_FILE, "w") as f:
        for domain in sorted(list(domains_set)):
            f.write(f"{domain}\n")

VALID_LINK_DOMAINS = load_domains()

# --- HELPER FUNCTIONS ---
def send_log(message: str, is_error: bool = False):
    if LOG_CHANNEL_ID:
        try:
            text = f"⚠️ **BOT ERROR** ⚠️\n\n<pre>{message}</pre>" if is_error else message
            bot.send_message(chat_id=LOG_CHANNEL_ID, text=text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Failed to send log message: {e}")

# ... (All other helper functions like get_blogger_service, upload_to_imagebb, etc. are here and correct) ...
def get_blogger_service():
    try:
        creds = Credentials(token=None, refresh_token=GOOGLE_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token", client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET, scopes=['https://www.googleapis.com/auth/blogger'])
        return build('blogger', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build Google service: {e}")
        send_log(f"Failed to build Google service:\n{traceback.format_exc()}", is_error=True)
        return None
def upload_to_imagebb(image_path):
    if not IMAGEBB_API_KEY: return None
    try:
        with open(image_path, "rb") as image_file:
            response = requests.post("https://api.imgbb.com/1/upload", params={"key": IMAGEBB_API_KEY}, files={"image": image_file}, timeout=30)
            response.raise_for_status()
            json_response = response.json()
            return json_response["data"]["url"] if json_response.get("success") else None
    except requests.RequestException as e:
        logger.error(f"ImageBB upload request failed: {e}")
        return None
def build_blog_post_html(image_url, caption_text, links_list):
    dynamic_buttons_html = ""
    if len(links_list) == 1: dynamic_buttons_html = f'<a href="{links_list[0]}" class="video-button" target="_blank">🎬 Watch Video</a>'
    elif len(links_list) > 1:
        for i, url in enumerate(links_list): dynamic_buttons_html += f'<a href="{url}" class="video-button" target="_blank">🎬 Watch Video {i + 1}</a>'
    footer_buttons_html = ""
    if TELEGRAM_CHANNEL_LINK: footer_buttons_html += f'<a href="{TELEGRAM_CHANNEL_LINK}" class="social-button telegram" target="_blank">Join All Channels</a>'
    if INSTAGRAM_LINK: footer_buttons_html += f'<a href="{INSTAGRAM_LINK}" class="social-button instagram" target="_blank">Follow on Instagram</a>'
    style_block = """<style>.post-container{text-align:center;font-family:sans-serif;margin:0 auto;max-width:700px;}.post-container img{max-width:100%;height:auto;border-radius:12px;margin-bottom:20px;box-shadow:0 4px 15px rgba(0,0,0,0.1);}.post-caption{font-size:1.1em;color:#444;line-height:1.6;padding:0 15px;margin-bottom:25px;text-align:left;}.button-container{margin-bottom:30px;}.video-button,.social-button{display:inline-block;padding:12px 28px;margin:8px;font-size:16px;font-weight:bold;color:#fff;border:none;border-radius:8px;text-decoration:none;transition:all .2s ease-in-out;box-shadow:0 2px 5px rgba(0,0,0,0.2);}.video-button:hover,.social-button:hover{transform:scale(1.05);box-shadow:0 4px 10px rgba(0,0,0,0.3);}.video-button{background-color:#ff4500;}.social-button.telegram{background-color:#0088cc;}.social-button.instagram{background:#d6249f;background:radial-gradient(circle at 30% 107%,#fdf4C97 0%,#fdf497 5%,#fd5949 45%,#d6249f 60%,#285aeb 90%);}</style>"""
    image_tag = f'<img src="{image_url}" alt="Post Image" />' if image_url else ""
    return f"""{style_block}<div class="post-container">{image_tag}<div class="post-caption">{caption_text.replace(os.linesep, "<br>")}</div><div class="button-container">{dynamic_buttons_html}</div><div class="footer-container">{footer_buttons_html}</div></div>"""
def process_and_publish_post(context: CallbackContext, title: str, caption_text: str, photo_path: str, links_list: list, user_name: str, source: str, chat_id=None):
    try:
        service = get_blogger_service()
        if not service:
            send_log(f"❌ {source.upper()} ERROR! Could not build Google Blogger service.", is_error=True)
            if source == 'manual' and chat_id: context.bot.send_message(chat_id=chat_id, text="Error: Could not connect to Google.")
            return
        image_url = None
        if photo_path and os.path.exists(photo_path):
            image_url = upload_to_imagebb(photo_path)
            if not image_url:
                if source == 'manual' and chat_id: context.bot.send_message(chat_id=chat_id, text="Error: Failed to upload image.")
                return
        body_html = build_blog_post_html(image_url, caption_text, links_list)
        body = {"kind": "blogger#post", "blog": {"id": BLOG_ID}, "title": title, "content": body_html}
        service.posts().insert(blogId=BLOG_ID, body=body, isDraft=False).execute()
        send_log(f"✅ {source.upper()} SUCCESS! Post '{title}' published by {user_name}.")
        if source == 'manual' and chat_id: context.bot.send_message(chat_id=chat_id, text=f"Success! Post '{title}' published.")
    except Exception:
        error_details = traceback.format_exc()
        send_log(f"❌ {source.upper()} ERROR! Failed to post '{title}'.\n\n{error_details}", is_error=True)
        if source == 'manual' and chat_id: context.bot.send_message(chat_id=chat_id, text=f"An unexpected error occurred.")
    finally:
        if photo_path and os.path.exists(photo_path): os.remove(photo_path)

# --- AUTOMATED CHANNEL POST HANDLER (REWRITTEN WITH DEBUG LOGS) ---
def channel_post_handler(update: Update, context: CallbackContext):
    if not update.channel_post: return
    post = update.channel_post
    chat_title = post.chat.title or f"ID:{post.chat_id}"

    send_log(f"ℹ️ AUTOMATION: [Step 1/5] Received a new post in channel '{chat_title}' ({post.chat_id}).")

    # Filter 1: Is it from a source channel?
    if post.chat_id not in SOURCE_CHANNEL_IDS:
        send_log(f"❌ AUTOMATION: [IGNORED] Post is from channel {post.chat_id}, which is not in the source list: {SOURCE_CHANNEL_IDS}.")
        return

    # Filter 2: Does it have media?
    if not (post.photo or post.video):
        send_log(f"❌ AUTOMATION: [IGNORED] Post in '{chat_title}' does not contain a photo or video.")
        return
        
    send_log(f"➡️ AUTOMATION: [Step 2/5] Post passed initial filters (source channel & media type).")

    full_caption = post.caption or ""
    all_urls = re.findall(r'https?://\S+', full_caption)
    
    # Filter 3: Does the caption contain any URLs at all?
    if not all_urls:
        send_log(f"❌ AUTOMATION: [IGNORED] No URLs were found in the post's caption.")
        return
        
    send_log(f"➡️ AUTOMATION: [Step 3/5] Found these URLs in the caption:\n`{all_urls}`")

    send_log(f"➡️ AUTOMATION: [Step 4/5] Checking URLs against this list of allowed domains:\n`{sorted(list(VALID_LINK_DOMAINS))}`")
    valid_urls = [url for url in all_urls if any(domain in url for domain in VALID_LINK_DOMAINS)]

    # Filter 4: Do any of the found URLs match our allowed domains?
    if not valid_urls:
        send_log(f"❌ AUTOMATION: [IGNORED] None of the found URLs matched the allowed domains list. Please use /addsite if needed.")
        return

    send_log(f"✅ AUTOMATION: [Step 5/5] Success! Found valid links: `{valid_urls}`. Proceeding to create blog post.")

    # --- If all checks pass, continue with the rest of the logic ---
    media_file = post.video.thumb.get_file() if post.video else post.photo[-1].get_file()
    
    clean_caption = re.sub(r'https?://\S+', '', full_caption).strip()
    junk_patterns = [r'join my channel', r'watch online', r'full video link', r'👇', r'👉', r'\(BY - @\S+\)']
    for pattern in junk_patterns:
        clean_caption = re.sub(pattern, '', clean_caption, flags=re.IGNORECASE)
    main_caption = "\n".join([line.strip() for line in clean_caption.split('\n') if line.strip()])

    if not main_caption:
        title = f"New Post from {chat_title}"
        send_log(f"⚠️ AUTOMATION: Could not extract a clean caption. Using fallback title: '{title}'")
    else:
        title = main_caption.split('\n')[0].strip()

    photo_path = f"temp_{media_file.file_id}.jpg"
    media_file.download(photo_path)
    process_and_publish_post(context, title, main_caption, photo_path, valid_urls, user_name=f"Channel '{chat_title}'", source="automation")


# --- MANUAL POSTING & ADMIN HANDLERS (No changes needed here) ---
GET_TITLE, GET_MEDIA, GET_CAPTION, GET_LINKS = range(4)
def start(update: Update, context: CallbackContext) -> int:
    send_log(f"MANUAL: New conversation started by {update.effective_user.first_name}.")
    context.user_data.clear()
    update.message.reply_text("Hi! Let's create a new blog post.\n\nFirst, what is the **title**?", parse_mode='Markdown')
    return GET_TITLE
def get_title(update: Update, context: CallbackContext) -> int:
    context.user_data['title'] = update.message.text
    update.message.reply_text("Great. Now, please send the photo or video for the post.\n\nOr, send /skip if you don't want to include an image.")
    return GET_MEDIA
def get_media(update: Update, context: CallbackContext) -> int:
    media_file = update.message.video.thumb.get_file() if update.message.video else update.message.photo[-1].get_file()
    photo_path = f"temp_{media_file.file_id}.jpg"
    media_file.download(photo_path)
    context.user_data['photo_path'] = photo_path
    update.message.reply_text("Media received. Next, send the **caption**.", parse_mode='Markdown')
    return GET_CAPTION
def skip_media(update: Update, context: CallbackContext) -> int:
    context.user_data['photo_path'] = None
    update.message.reply_text("No media will be used. Now, please send the **caption**.", parse_mode='Markdown')
    return GET_CAPTION
def media_prompt(update: Update, context: CallbackContext):
    update.message.reply_text("Please send a photo/video, or use /skip.")
    return GET_MEDIA
def get_caption(update: Update, context: CallbackContext) -> int:
    context.user_data['caption'] = update.message.text
    update.message.reply_text("Caption saved. Finally, send the video **link(s)**. You can send multiple links, one per line.", parse_mode='Markdown')
    return GET_LINKS
def create_manual_post(update: Update, context: CallbackContext) -> int:
    links_text = update.message.text
    valid_urls = re.findall(r'https?://\S+', links_text)
    if not valid_urls:
        update.message.reply_text("No valid links found. Please send the link(s) again or /cancel.")
        return GET_LINKS
    title = context.user_data.get('title', 'No Title')
    caption_text = context.user_data.get('caption', '')
    photo_path = context.user_data.get('photo_path')
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    update.message.reply_text(f"Got it! Publishing '{title}' to your blog...")
    process_and_publish_post(context, title, caption_text, photo_path, valid_urls, user_name, "manual", chat_id)
    context.user_data.clear()
    return ConversationHandler.END
def cancel(update: Update, context: CallbackContext) -> int:
    if 'photo_path' in context.user_data and context.user_data['photo_path'] and os.path.exists(context.user_data['photo_path']): os.remove(context.user_data['photo_path'])
    context.user_data.clear()
    update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END
def add_site(update: Update, context: CallbackContext):
    if str(update.effective_user.id) != ADMIN_ID: return
    if not context.args:
        update.message.reply_text("Usage: /addsite <domain.com>")
        return
    domain_to_add = context.args[0].lower().strip()
    if domain_to_add in VALID_LINK_DOMAINS:
        update.message.reply_text(f"✅ Domain '{domain_to_add}' is already in the list.")
    else:
        VALID_LINK_DOMAINS.add(domain_to_add)
        save_domains(VALID_LINK_DOMAINS)
        update.message.reply_text(f"✅ Domain '{domain_to_add}' added successfully.")
def remove_site(update: Update, context: CallbackContext):
    if str(update.effective_user.id) != ADMIN_ID: return
    if not context.args:
        update.message.reply_text("Usage: /removesite <domain.com>")
        return
    domain_to_remove = context.args[0].lower().strip()
    if domain_to_remove in VALID_LINK_DOMAINS:
        VALID_LINK_DOMAINS.discard(domain_to_remove)
        save_domains(VALID_LINK_DOMAINS)
        update.message.reply_text(f"✅ Domain '{domain_to_remove}' removed successfully.")
    else:
        update.message.reply_text(f"❌ Domain '{domain_to_remove}' not found.")
def list_sites(update: Update, context: CallbackContext):
    if str(update.effective_user.id) != ADMIN_ID: return
    if not VALID_LINK_DOMAINS:
        update.message.reply_text("The list of allowed domains is empty.")
    else:
        message = "📝 **Currently Allowed Domains:**\n\n" + "<code>" + "\n".join(sorted(list(VALID_LINK_DOMAINS))) + "</code>"
        update.message.reply_text(message, parse_mode='HTML')
def help_command(update: Update, context: CallbackContext):
    help_text = "Hello! I am your Blogger Poster Bot.\n\n**User Commands:**\n/start - Manually create a new post.\n/cancel - Stop the current posting process.\n/help - Show this message."
    admin_help_text = "\n\n**Admin Commands:**\n/addsite `<domain.com>`\n/removesite `<domain.com>`\n/listsites"
    if str(update.effective_user.id) == ADMIN_ID: help_text += admin_help_text
    update.message.reply_text(help_text, parse_mode='Markdown')

# --- FLASK WEB SERVER & DISPATCHER SETUP ---
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, use_context=True)
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        GET_TITLE: [MessageHandler(Filters.text & ~Filters.command, get_title)],
        GET_MEDIA: [MessageHandler(Filters.photo | Filters.video, get_media), CommandHandler('skip', skip_media), MessageHandler(Filters.text & ~Filters.command, media_prompt)],
        GET_CAPTION: [MessageHandler(Filters.text & ~Filters.command, get_caption)],
        GET_LINKS: [MessageHandler(Filters.text & ~Filters.command, create_manual_post)],
    },
    fallbacks=[CommandHandler('cancel', cancel)], name="manual_blogger_conversation", persistent=False
)
dispatcher.add_handler(conv_handler)
dispatcher.add_handler(MessageHandler((Filters.photo | Filters.video) & Filters.chat_type.channel, channel_post_handler))
dispatcher.add_handler(CommandHandler('addsite', add_site))
dispatcher.add_handler(CommandHandler('removesite', remove_site))
dispatcher.add_handler(CommandHandler('listsites', list_sites))
dispatcher.add_handler(CommandHandler('help', help_command))

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    dispatcher.process_update(Update.de_json(request.get_json(force=True), bot))
    return 'ok'
@app.route('/')
def index(): return 'Bot is running!'
if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}")
        logger.info(f"Webhook set to {WEBHOOK_URL}")
        send_log("🚀 Bot has been deployed/restarted with ENHANCED debug logging.")
    else:
        logger.warning("WEBHOOK_URL not set.")
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)