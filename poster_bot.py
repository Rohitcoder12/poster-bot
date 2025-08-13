import os
import pickle
import base64 # Used for encoding/decoding the credentials string
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
)
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- CONFIGURATION (from Environment Variables) ---
# We no longer hardcode secrets. They will be set in the deployment service.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BLOG_ID = os.environ.get("BLOG_ID")
GOOGLE_CREDS_STRING = os.environ.get("GOOGLE_CREDS_STRING")

# Define conversation states
GET_TITLE, GET_PHOTO, GET_CAPTION = range(3)

# --- GOOGLE AUTHENTICATION ---
# This function is now updated to work in a stateless cloud environment
def get_blogger_service():
    creds = None
    
    # Priority 1: Use the credential string from the environment variable (for cloud deployment)
    if GOOGLE_CREDS_STRING:
        creds_decoded = base64.b64decode(GOOGLE_CREDS_STRING)
        creds = pickle.loads(creds_decoded)
    
    # Priority 2: Use the local token.pickle file (for local setup/testing)
    elif os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    # If there are no valid credentials, we need to log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # This part will only run during the one-time local setup
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', ['https://www.googleapis.com/auth/blogger'])
            creds = flow.run_local_server(port=0)
        
        # After a successful login, save the credentials.
        # If running locally, create token.pickle AND print the string for deployment.
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
        
        # --- THIS IS THE MAGIC PART FOR DEPLOYMENT ---
        # We encode the credentials object into a printable string
        creds_encoded = base64.b64encode(pickle.dumps(creds)).decode('utf-8')
        print("--- COPY YOUR GOOGLE CREDENTIALS STRING BELOW ---")
        print(creds_encoded)
        print("--- END OF STRING ---")
        # In a deployed environment, this part won't run because GOOGLE_CREDS_STRING will already exist.

    service = build('blogger', 'v3', credentials=creds)
    return service

# --- BOT HANDLERS (These remain the same as before) ---

def start(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "Hi! Let's create a new blog post. What is the title?\nSend /cancel to stop."
    )
    return GET_TITLE

def get_title(update: Update, context: CallbackContext) -> int:
    context.user_data['title'] = update.message.text
    update.message.reply_text(
        f"Title: '{context.user_data['title']}'.\nNow, send the photo."
    )
    return GET_PHOTO

def get_photo(update: Update, context: CallbackContext) -> int:
    # Note: On a stateless server, this file is temporary and will be gone after the function ends.
    photo_file = update.message.photo[-1].get_file()
    photo_path = f"{photo_file.file_id}.jpg"
    photo_file.download(photo_path)
    context.user_data['photo_path'] = photo_path
    
    update.message.reply_text(
        "Photo received. Now, what's the caption? You can include links."
    )
    return GET_CAPTION

def get_caption(update: Update, context: CallbackContext) -> int:
    context.user_data['caption'] = update.message.text
    update.message.reply_text("Got it! Publishing to your blog...")

    try:
        service = get_blogger_service()
        title = context.user_data['title']
        caption = context.user_data['caption']
        photo_path = context.user_data['photo_path']

        # As before, a full solution requires uploading the image to a hosting service
        # and getting a URL. We will post the text content for now.
        body_html = f"<p>{caption.replace(os.linesep, '<br>')}</p>"

        body = {
            "kind": "blogger#post",
            "blog": {"id": BLOG_ID},
            "title": title,
            "content": body_html
        }

        posts = service.posts()
        posts.insert(blogId=BLOG_ID, body=body, isDraft=False).execute()
        
        update.message.reply_text(
            f"Success! Post '{title}' published.",
            reply_markup=ReplyKeyboardRemove(),
        )
        
        # Clean up the temporary photo file
        os.remove(photo_path)

    except Exception as e:
        update.message.reply_text(f"An error occurred: {e}")
        print(f"Error: {e}")

    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "Operation cancelled.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main() -> None:
    if not all([TELEGRAM_TOKEN, BLOG_ID]):
        print("ERROR: TELEGRAM_TOKEN and BLOG_ID environment variables must be set.")
        return

    # This check is crucial for deployment
    if not GOOGLE_CREDS_STRING and not os.path.exists('credentials.json'):
         print("ERROR: GOOGLE_CREDS_STRING must be set for cloud, or credentials.json must exist for local setup.")
         return

    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_TITLE: [MessageHandler(Filters.text & ~Filters.command, get_title)],
            GET_PHOTO: [MessageHandler(Filters.photo, get_photo)],
            GET_CAPTION: [MessageHandler(Filters.text & ~Filters.command, get_caption)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    dispatcher.add_handler(conv_handler)
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
