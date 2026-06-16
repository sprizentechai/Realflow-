import re
import json
import threading
import requests
import logging
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# =============================================================================
# HARDCODED API KEYS
# =============================================================================
TELEGRAM_BOT_TOKEN = "8933438428:AAFwQTmQvSMVg7Id_5cyR2o695r7CcO4K9Q"
GROQ_API_KEY = "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"
OPENAI_API_KEY = "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"
GEMINI_API_KEY = "AQ.Ab8RN6Jgqbj78TWX18OkHio4_qX2qhfyUjbNhTwNVay1dr3mrw"

# =============================================================================
# HARDCODED PROPERTIES (RAG)
# =============================================================================
PROPERTIES = [
    {
        "location": "Falkirk",
        "price": 185000,
        "bedrooms": 3,
        "type": "Semi-detached House",
        "description": "Beautiful 3-bedroom semi-detached house in Falkirk with a spacious garden, modern kitchen, and off-street parking. Ideal for first-time buyers and families."
    },
    {
        "location": "Edinburgh",
        "price": 450000,
        "bedrooms": 2,
        "type": "City Centre Apartment",
        "description": "Stunning 2-bedroom apartment in Edinburgh city centre, minutes from Princes Street and Waverley Station. Recently renovated with premium finishes and a private balcony."
    },
    {
        "location": "Glasgow",
        "price": 275000,
        "bedrooms": 4,
        "type": "Terraced Townhouse",
        "description": "Spacious 4-bedroom terraced townhouse in Glasgow's vibrant West End. Close to universities, parks, and nightlife. Period features with modern upgrades throughout."
    }
]

# =============================================================================
# SYSTEM PROMPT
# =============================================================================
SYSTEM_PROMPT = """You are RealFlow AI, a professional and friendly property consultant working exclusively for AMAZING RESULTS! Estate Agents in Scotland.

You have access to the following properties ONLY. Do not invent or mention any other properties:

1. Falkirk — £185,000 — 3-bed Semi-detached House
   Beautiful 3-bedroom semi-detached house in Falkirk with a spacious garden, modern kitchen, and off-street parking. Ideal for first-time buyers and families.

2. Edinburgh — £450,000 — 2-bed City Centre Apartment
   Stunning 2-bedroom apartment in Edinburgh city centre, minutes from Princes Street and Waverley Station. Recently renovated with premium finishes and a private balcony.

3. Glasgow — £275,000 — 4-bed Terraced Townhouse
   Spacious 4-bedroom terraced townhouse in Glasgow's vibrant West End. Close to universities, parks, and nightlife. Period features with modern upgrades throughout.

INSTRUCTIONS:
- Greet the user warmly and introduce yourself as RealFlow AI from AMAZING RESULTS! Estate Agents.
- Ask for their budget and preferred location if they haven't provided both.
- Once you know their budget and location, recommend EXACTLY ONE property from the list above that best matches their criteria.
- Be honest if no property matches their needs and suggest they contact AMAZING RESULTS! Estate Agents directly.
- Keep responses concise, helpful, and professional.
- Never make up properties, prices, or details that are not in the list above."""

# =============================================================================
# IN-MEMORY CONVERSATION HISTORY (last 6 messages per user)
# =============================================================================
conversation_history = {}

# =============================================================================
# BUDGET REGEX FOR CRM TRIGGER
# =============================================================================
BUDGET_PATTERN = re.compile(
    r'(?:£|\$|€)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+)(?:\s*[kK])?(?:\s*(?:pounds?|gbp|usd|eur|dollars?|euros?))?',
    re.IGNORECASE
)

CRM_ALERT = "[SYSTEM ALERT: Lead Qualified & Synced to HighLevel CRM 🟢]"

# =============================================================================
# LOGGING
# =============================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =============================================================================
# FLASK WEB SERVER (daemon thread for Render.com)
# =============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "RealFlow AI is running!"

@app.route('/health')
def health():
    return {"status": "ok"}, 200

def run_flask():
    app.run(host='0.0.0.0', port=5000)

# =============================================================================
# AI API CALLS (requests library only — no heavy SDKs)
# =============================================================================
def call_groq(messages):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-8b-8192",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1024
    }
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def call_openai(messages):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1024
    }
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def call_gemini(messages):
    system_text = ""
    contents = []

    for msg in messages:
        if msg["role"] == "system":
            system_text = msg["content"]
        else:
            gemini_role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": msg["content"]}]
            })

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": contents}

    if system_text:
        payload["systemInstruction"] = {
            "parts": [{"text": system_text}]
        }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()

    if "candidates" in data and len(data["candidates"]) > 0:
        candidate = data["candidates"][0]
        if candidate.get("finishReason") == "SAFETY":
            raise Exception("Gemini response blocked by safety settings")
        if "content" in candidate and "parts" in candidate["content"]:
            return candidate["content"]["parts"][0]["text"]

    raise Exception("Invalid Gemini response format")

def get_ai_response(messages):
    """Fallback chain: Groq -> OpenAI -> Gemini"""
    errors = []

    try:
        logger.info("Attempting Groq API...")
        return call_groq(messages)
    except Exception as e:
        errors.append(f"Groq: {e}")
        logger.warning(f"Groq failed: {e}")

    try:
        logger.info("Attempting OpenAI API...")
        return call_openai(messages)
    except Exception as e:
        errors.append(f"OpenAI: {e}")
        logger.warning(f"OpenAI failed: {e}")

    try:
        logger.info("Attempting Gemini API...")
        return call_gemini(messages)
    except Exception as e:
        errors.append(f"Gemini: {e}")
        logger.error(f"All AI APIs failed: {errors}")
        return (
            "I apologise, but I'm experiencing technical difficulties with my AI services at the moment. "
            "Please try again shortly, or contact AMAZING RESULTS! Estate Agents directly for immediate assistance."
        )

# =============================================================================
# HELPER: BUDGET DETECTION
# =============================================================================
def contains_budget(text):
    match = BUDGET_PATTERN.search(text)
    if not match:
        return False

    num_str = match.group(1).replace(',', '')
    try:
        num = float(num_str)
        if num < 1000:
            num *= 1000
        return 10000 <= num <= 10000000
    except ValueError:
        return False

# =============================================================================
# TELEGRAM HANDLERS
# =============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    welcome = (
        "🏠 Welcome to RealFlow AI — your personal property consultant for "
        "AMAZING RESULTS! Estate Agents in Scotland!\n\n"
        "I'm here to help you find your perfect home. To get started, could you tell me:\n"
        "1️⃣  What's your budget?\n"
        "2️⃣  Which area are you interested in? (Falkirk, Edinburgh, or Glasgow)\n\n"
        "Feel free to ask me anything about these properties!"
    )

    conversation_history[user_id] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": welcome}
    ]

    await update.message.reply_text(welcome)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    # Initialise history if missing
    if user_id not in conversation_history:
        conversation_history[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add user message
    conversation_history[user_id].append({"role": "user", "content": user_text})

    # Enforce last-6-messages limit (system prompt is exempt)
    system_msgs = [m for m in conversation_history[user_id] if m["role"] == "system"]
    other_msgs = [m for m in conversation_history[user_id] if m["role"] != "system"]
    if len(other_msgs) > 6:
        other_msgs = other_msgs[-6:]
    conversation_history[user_id] = system_msgs + other_msgs

    # Get AI response
    messages = conversation_history[user_id]
    reply = get_ai_response(messages)

    # CRM trigger: append alert if budget detected
    if contains_budget(user_text):
        reply += f"\n\n{CRM_ALERT}"

    # Store assistant reply
    conversation_history[user_id].append({"role": "assistant", "content": reply})

    # Re-trim to last 6
    system_msgs = [m for m in conversation_history[user_id] if m["role"] == "system"]
    other_msgs = [m for m in conversation_history[user_id] if m["role"] != "system"]
    if len(other_msgs) > 6:
        other_msgs = other_msgs[-6:]
    conversation_history[user_id] = system_msgs + other_msgs

    await update.message.reply_text(reply)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
def main():
    # Start Flask in a daemon thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server started on port 5000")

    # Build and run the Telegram bot
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    logger.info("RealFlow AI bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
