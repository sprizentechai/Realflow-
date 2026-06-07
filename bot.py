"""
================================================================================
    RealFlow AI - Production-Ready Telegram Real Estate Bot
================================================================================
    Bot Name    : RealFlow AI
    Company     : AMAZING RESULTS! Estate Agents in Scotland
    Description : AI-powered property consultant with Multi-LLM API rotation,
                  in-memory conversation history, and lead qualification.
    Hosting     : Render.com + UptimeRobot (24/7 Free Hosting Ready)

    Architecture:
    - Flask web server (Port 5000) for health-check pings
    - pyTelegramBotAPI for Telegram interface
    - Multi-LLM rotation: Groq API, Google Gemini API, Cohere API
    - Automatic fallback on API failure/rate-limit
    - In-memory per-user conversation history (last 5 messages)
    - Regex-based budget detection with CRM lead qualification alert
================================================================================
"""

import os
import re
import sys
import json
import time
import random
import logging
import threading
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import requests
import telebot
from flask import Flask


# ==============================================================================
#  SECTION 1: CONFIGURATION & API KEYS
# ==============================================================================

# --- Telegram Bot Token ---
# Get your bot token from @BotFather on Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

# --- LLM API Keys (Set via environment variables or paste directly) ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "YOUR_GROQ_API_KEY_HERE")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
COHERE_API_KEY = os.environ.get("COHERE_API_KEY", "YOUR_COHERE_API_KEY_HERE")

# --- Flask Server Configuration ---
FLASK_PORT = int(os.environ.get("PORT", 5000))
FLASK_HOST = "0.0.0.0"

# --- Bot Metadata ---
BOT_NAME = "RealFlow AI"
COMPANY_NAME = "AMAZING RESULTS! Estate Agents in Scotland"
COMPANY_TAGLINE = "Your Dream Home in Scotland Awaits!"

# --- API Rotation Settings ---
API_TIMEOUT_SECONDS = 30          # Max wait time per API call
MAX_RETRIES_PER_API = 2           # Retry attempts per provider before fallback
ENABLE_RANDOM_ROTATION = True     # True=random pick, False=round-robin

# --- Conversation Settings ---
MAX_CONVERSATION_HISTORY = 5      # Keep last N messages per user
CONVERSATION_TTL_HOURS = 24       # Clear history after N hours of inactivity

# --- Budget Detection Regex ---
BUDGET_REGEX_PATTERNS = [
    r"£\s*([\d,]+(?:\.\d{1,2})?)",      # £250,000 or £250000
    r"(\d[\d,]*)\s*k",                   # 300k or 250K
    r"(\d[\d,]*)\s*thousand",            # 300 thousand
    r"budget\s*(?:of\s*)?£?\s*([\d,]+)",  # budget of 250000
    r"(\d{3,6})\s*(?:pounds?|gbp)",       # 250000 pounds
]

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("RealFlowAI")


# ==============================================================================
#  SECTION 2: HARDCODED RAG PROPERTY DATABASE (Scotland)
# ==============================================================================

PROPERTY_DATABASE: List[Dict[str, Any]] = [
    {
        "id": "PROP-001",
        "title": "Stunning 3-Bedroom Victorian Townhouse",
        "location": "Edinburgh, EH1 - Old Town",
        "price": 285000,
        "price_display": "£285,000",
        "bedrooms": 3,
        "bathrooms": 2,
        "type": "Townhouse",
        "description": (
            "A beautifully preserved Victorian townhouse in Edinburgh's historic Old Town. "
            "Features original fireplaces, high ceilings, modern kitchen, private garden, "
            "and easy access to Edinburgh Castle and the Royal Mile."
        ),
        "features": ["Garden", "Period Features", "City Centre", "Near Schools"],
        "match_keywords": ["edinburgh", "city", "townhouse", "victorian", "old town"]
    },
    {
        "id": "PROP-002",
        "title": "Modern 2-Bedroom Waterfront Apartment",
        "location": "Glasgow, G3 - Finnieston",
        "price": 195000,
        "price_display": "£195,000",
        "bedrooms": 2,
        "bathrooms": 2,
        "type": "Apartment",
        "description": (
            "A sleek waterfront apartment in trendy Finnieston with floor-to-ceiling windows "
            "overlooking the River Clyde. Open-plan living, concierge service, gym access, "
            "and walking distance to SEC and Hydro."
        ),
        "features": ["Waterfront", "Gym", "Concierge", "Modern", "Riverside"],
        "match_keywords": ["glasgow", "apartment", "flat", "waterfront", "finnieston"]
    },
    {
        "id": "PROP-003",
        "title": "Spacious 4-Bedroom Family Detached Home",
        "location": "Aberdeen, AB15 - Cults",
        "price": 450000,
        "price_display": "£450,000",
        "bedrooms": 4,
        "bathrooms": 3,
        "type": "Detached House",
        "description": (
            "An impressive detached family home in the prestigious Cults area of Aberdeen. "
            "Large driveway, double garage, south-facing garden, four double bedrooms "
            "(master en-suite), and top-rated local schools nearby."
        ),
        "features": ["Garden", "Garage", "Near Schools", "Spacious", "Prestigious Area"],
        "match_keywords": ["aberdeen", "family", "detached", "house", "cults"]
    },
    {
        "id": "PROP-004",
        "title": "Cosy 1-Bedroom Highland Cottage",
        "location": "Inverness, IV2 - Loch Ness Area",
        "price": 165000,
        "price_display": "£165,000",
        "bedrooms": 1,
        "bathrooms": 1,
        "type": "Cottage",
        "description": (
            "A charming traditional Highland cottage near Loch Ness. Recently renovated with "
            "modern heating, stone walls, wood-burning stove, and breathtaking Highland views. "
            "Perfect for a holiday home or peaceful retreat."
        ),
        "features": ["Scenic Views", "Wood Burner", "Renovated", "Holiday Home"],
        "match_keywords": ["inverness", "highland", "cottage", "loch ness", "holiday"]
    },
    {
        "id": "PROP-005",
        "title": "Luxury 5-Bedroom New-Build Villa",
        "location": "Stirling, FK8 - Bridge of Allan",
        "price": 625000,
        "price_display": "£625,000",
        "bedrooms": 5,
        "bathrooms": 4,
        "type": "Villa",
        "description": (
            "A stunning new-build villa in the sought-after Bridge of Allan. Bespoke kitchen, "
            "bi-fold doors, underfloor heating, home office, triple garage, and panoramic views "
            "of Stirling Castle and the Ochil Hills."
        ),
        "features": ["New Build", "Garage", "Home Office", "Panoramic Views", "Luxury"],
        "match_keywords": ["stirling", "villa", "luxury", "bridge of allan", "new build"]
    },
    {
        "id": "PROP-006",
        "title": "Investment 3-Bedroom Tenement Flat",
        "location": "Dundee, DD1 - City Centre",
        "price": 155000,
        "price_display": "£155,000",
        "bedrooms": 3,
        "bathrooms": 1,
        "type": "Tenement Flat",
        "description": (
            "A spacious traditional tenement flat in Dundee city centre with original features. "
            "High rental demand area, close to universities and V&A Dundee. Excellent buy-to-let "
            "investment opportunity."
        ),
        "features": ["Investment", "Near University", "High Rental Demand", "Period Features"],
        "match_keywords": ["dundee", "investment", "flat", "tenement", "rental"]
    },
    {
        "id": "PROP-007",
        "title": "Charming 2-Bedroom Coastal Bungalow",
        "location": "Ayr, KA7 - Prestwick Beach",
        "price": 220000,
        "price_display": "£220,000",
        "bedrooms": 2,
        "bathrooms": 1,
        "type": "Bungalow",
        "description": (
            "A delightful single-storey bungalow just moments from Prestwick Beach. "
            "Well-maintained gardens, conservatory, driveway for two cars, and a short walk "
            "to coastal promenade and local golf courses."
        ),
        "features": ["Near Beach", "Garden", "Single Storey", "Driveway", "Golf Nearby"],
        "match_keywords": ["ayr", "coastal", "bungalow", "beach", "prestwick"]
    },
    {
        "id": "PROP-008",
        "title": "Contemporary 2-Bedroom Penthouse",
        "location": "Perth, PH1 - City Centre",
        "price": 275000,
        "price_display": "£275,000",
        "bedrooms": 2,
        "bathrooms": 2,
        "type": "Penthouse",
        "description": (
            "A rare penthouse apartment in the heart of Perth with a wraparound terrace "
            "offering stunning views over the River Tay. Designer kitchen, two bathrooms, "
            "allocated parking, and lift access."
        ),
        "features": ["Terrace", "River Views", "Lift Access", "Parking", "Designer"],
        "match_keywords": ["perth", "penthouse", "terrace", "river", "apartment"]
    },
]


def format_property_for_prompt(property_data: Dict[str, Any]) -> str:
    """Format a single property into a readable string for the LLM context."""
    return (
        f"[{property_data['id']}] {property_data['title']}\n"
        f"    Location: {property_data['location']}\n"
        f"    Price: {property_data['price_display']}\n"
        f"    Bedrooms: {property_data['bedrooms']} | Bathrooms: {property_data['bathrooms']}\n"
        f"    Type: {property_data['type']}\n"
        f"    Features: {', '.join(property_data['features'])}\n"
        f"    Description: {property_data['description']}"
    )


def get_all_properties_text() -> str:
    """Get all properties formatted for the system prompt."""
    return "\n\n".join(format_property_for_prompt(p) for p in PROPERTY_DATABASE)


def find_matching_property(user_message: str, budget: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Find the best matching property based on user query keywords and budget.
    Returns exactly ONE property - the best match.
    """
    message_lower = user_message.lower()
    words = set(re.findall(r'[a-z]+', message_lower))
    
    scored_properties = []
    for prop in PROPERTY_DATABASE:
        score = 0
        # Keyword matching
        for kw in prop["match_keywords"]:
            if kw in message_lower:
                score += 3
        # Budget proximity (closer = higher score)
        if budget is not None:
            diff = abs(prop["price"] - budget)
            if diff <= budget * 0.1:    # Within 10%
                score += 10
            elif diff <= budget * 0.2:  # Within 20%
                score += 5
            elif diff <= budget * 0.3:  # Within 30%
                score += 2
        scored_properties.append((score, prop))
    
    scored_properties.sort(key=lambda x: x[0], reverse=True)
    
    if scored_properties and scored_properties[0][0] > 0:
        return scored_properties[0][1]
    
    # Default fallback: return the most affordable property
    return PROPERTY_DATABASE[5]  # Dundee investment flat as default


# ==============================================================================
#  SECTION 3: CONVERSATION HISTORY MANAGER (In-Memory)
# ==============================================================================

class ConversationManager:
    """
    Manages in-memory conversation history per user.
    - Stores last N messages per user (N = MAX_CONVERSATION_HISTORY)
    - Auto-clears stale conversations after TTL hours
    - Thread-safe using locks
    """

    def __init__(self, max_history: int = MAX_CONVERSATION_HISTORY, ttl_hours: int = CONVERSATION_TTL_HOURS):
        self.max_history = max_history
        self.ttl_hours = ttl_hours
        self._conversations: Dict[int, deque] = {}
        self._last_activity: Dict[int, datetime] = {}
        self._lock = threading.Lock()
        self._cleanup_interval = 3600  # Run cleanup every hour
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """Start a background thread to clean up stale conversations."""
        def cleanup_worker():
            while True:
                time.sleep(self._cleanup_interval)
                self._cleanup_stale()
        
        thread = threading.Thread(target=cleanup_worker, daemon=True, name="ConversationCleanup")
        thread.start()

    def _cleanup_stale(self):
        """Remove conversations that have been inactive for longer than TTL."""
        now = datetime.now()
        stale_users = []
        with self._lock:
            for user_id, last_time in self._last_activity.items():
                if (now - last_time).total_seconds() > self.ttl_hours * 3600:
                    stale_users.append(user_id)
            for user_id in stale_users:
                del self._conversations[user_id]
                del self._last_activity[user_id]
        if stale_users:
            logger.info(f"Cleaned up {len(stale_users)} stale conversation(s).")

    def add_message(self, user_id: int, role: str, content: str):
        """Add a message to the user's conversation history."""
        with self._lock:
            if user_id not in self._conversations:
                self._conversations[user_id] = deque(maxlen=self.max_history)
            self._conversations[user_id].append({"role": role, "content": content})
            self._last_activity[user_id] = datetime.now()

    def get_history(self, user_id: int) -> List[Dict[str, str]]:
        """Get the conversation history for a user as a list."""
        with self._lock:
            if user_id not in self._conversations:
                return []
            self._last_activity[user_id] = datetime.now()
            return list(self._conversations[user_id])

    def clear_history(self, user_id: int):
        """Clear conversation history for a specific user."""
        with self._lock:
            self._conversations.pop(user_id, None)
            self._last_activity.pop(user_id, None)

    def get_stats(self) -> Dict[str, int]:
        """Get conversation statistics."""
        with self._lock:
            return {
                "active_conversations": len(self._conversations),
                "max_history_per_user": self.max_history,
                "ttl_hours": self.ttl_hours
            }


# Global conversation manager instance
conversation_mgr = ConversationManager()


# ==============================================================================
#  SECTION 4: MULTI-LLM API ROTATION MANAGER
# ==============================================================================

class LLMProvider:
    """Base class for LLM API providers."""
    
    def __init__(self, name: str, api_key: str, enabled: bool = True):
        self.name = name
        self.api_key = api_key
        self.enabled = enabled and api_key and api_key.startswith("gsk_") or api_key and len(api_key) > 10
        self.failure_count = 0
        self.success_count = 0
        self.last_error: Optional[str] = None
    
    def is_available(self) -> bool:
        return self.enabled and self.api_key and self.api_key not in ("YOUR_GROQ_API_KEY_HERE", "YOUR_GEMINI_API_KEY_HERE", "YOUR_COHERE_API_KEY_HERE", "")
    
    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> Optional[str]:
        raise NotImplementedError
    
    def record_success(self):
        self.success_count += 1
        self.failure_count = 0
        self.last_error = None
    
    def record_failure(self, error: str):
        self.failure_count += 1
        self.last_error = error
        logger.warning(f"[{self.name}] Failure #{self.failure_count}: {error}")


class GroqProvider(LLMProvider):
    """Groq API Provider - Ultra-fast LLM inference."""
    
    def __init__(self, api_key: str):
        super().__init__("Groq", api_key)
        self.base_url = "https://api.groq.com/openai/v1"
        self.model = "llama-3.3-70b-versatile"  # Fast, capable model on free tier
    
    def is_available(self) -> bool:
        return super().is_available() and self.api_key.startswith("gsk_")
    
    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> Optional[str]:
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system_prompt}] + messages,
                "temperature": 0.7,
                "max_tokens": 1024
            }
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=API_TIMEOUT_SECONDS
            )
            if response.status_code == 429:
                raise Exception("Rate limited (429)")
            response.raise_for_status()
            data = response.json()
            result = data["choices"][0]["message"]["content"]
            self.record_success()
            return result
        except Exception as e:
            self.record_failure(str(e))
            return None


class GeminiProvider(LLMProvider):
    """Google Gemini API Provider - Google's AI model."""
    
    def __init__(self, api_key: str):
        super().__init__("Gemini", api_key)
        self.model = "gemini-1.5-flash"  # Free tier model
    
    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> Optional[str]:
        try:
            # Convert messages to Gemini format
            gemini_contents = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                gemini_contents.append({"role": role, "parts": [{"text": msg["content"]}]})
            
            # Gemini uses systemInstruction in the payload
            payload = {
                "contents": gemini_contents,
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1024
                }
            }
            
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
                f"?key={self.api_key}"
            )
            response = requests.post(
                url,
                json=payload,
                timeout=API_TIMEOUT_SECONDS,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code == 429:
                raise Exception("Rate limited (429)")
            response.raise_for_status()
            data = response.json()
            
            # Extract text from Gemini response
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                result = " ".join(part.get("text", "") for part in parts)
                self.record_success()
                return result
            return None
        except Exception as e:
            self.record_failure(str(e))
            return None


class CohereProvider(LLMProvider):
    """Cohere API Provider - Command R model on free tier."""
    
    def __init__(self, api_key: str):
        super().__init__("Cohere", api_key)
        self.model = "command-r"
    
    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> Optional[str]:
        try:
            # Cohere Chat API format
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Extract the last user message as the main message
            chat_history = []
            last_user_message = ""
            for msg in messages:
                if msg["role"] == "user":
                    chat_history.append({"role": "USER", "message": msg["content"]})
                    last_user_message = msg["content"]
                else:
                    chat_history.append({"role": "CHATBOT", "message": msg["content"]})
            
            # Remove the last user message from history (it goes in 'message' field)
            if chat_history and chat_history[-1]["role"] == "USER":
                chat_history.pop()
            
            payload = {
                "model": self.model,
                "message": last_user_message or "Hello",
                "chat_history": chat_history,
                "preamble": system_prompt,
                "temperature": 0.7,
                "max_tokens": 1024
            }
            
            response = requests.post(
                "https://api.cohere.com/v1/chat",
                headers=headers,
                json=payload,
                timeout=API_TIMEOUT_SECONDS
            )
            if response.status_code == 429:
                raise Exception("Rate limited (429)")
            response.raise_for_status()
            data = response.json()
            result = data.get("text", "")
            self.record_success()
            return result
        except Exception as e:
            self.record_failure(str(e))
            return None


class LLMManager:
    """
    Smart API Router/Manager:
    - Maintains multiple LLM providers
    - Random or round-robin selection
    - Automatic fallback on failure
    - Tracks API usage statistics
    """
    
    def __init__(self):
        self.providers: List[LLMProvider] = []
        self._round_robin_index = 0
        self._lock = threading.Lock()
        self._total_requests = 0
        self._failed_requests = 0
        
    def register_provider(self, provider: LLMProvider):
        """Register an LLM provider."""
        self.providers.append(provider)
        logger.info(f"Registered LLM provider: {provider.name} (enabled={provider.is_available()})")
    
    def get_available_providers(self) -> List[LLMProvider]:
        """Get list of currently available (key-configured) providers."""
        return [p for p in self.providers if p.is_available()]
    
    def select_provider(self) -> Optional[LLMProvider]:
        """Select a provider using random or round-robin strategy."""
        available = self.get_available_providers()
        if not available:
            return None
        
        with self._lock:
            if ENABLE_RANDOM_ROTATION:
                return random.choice(available)
            else:
                provider = available[self._round_robin_index % len(available)]
                self._round_robin_index += 1
                return provider
    
    def generate_response(self, messages: List[Dict[str, str]], system_prompt: str) -> Tuple[Optional[str], str]:
        """
        Generate a response with automatic fallback.
        Returns: (response_text, provider_name_used)
        """
        self._total_requests += 1
        available = self.get_available_providers()
        
        if not available:
            logger.error("No LLM providers available. Check your API keys.")
            self._failed_requests += 1
            return None, "None"
        
        # Try each available provider until one succeeds
        tried = set()
        while len(tried) < len(available):
            provider = self.select_provider()
            if provider.name in tried:
                # If we've tried this one, pick another
                remaining = [p for p in available if p.name not in tried]
                if not remaining:
                    break
                provider = remaining[0]
            
            tried.add(provider.name)
            logger.info(f"[LLM Router] Trying provider: {provider.name} (successes={provider.success_count}, failures={provider.failure_count})")
            
            for attempt in range(1, MAX_RETRIES_PER_API + 1):
                result = provider.generate(messages, system_prompt)
                if result:
                    logger.info(f"[LLM Router] Success with {provider.name} on attempt {attempt}")
                    return result, provider.name
                time.sleep(1)  # Brief pause before retry
            
            logger.warning(f"[LLM Router] Provider {provider.name} exhausted all retries.")
        
        # All providers failed
        self._failed_requests += 1
        logger.error("[LLM Router] All providers failed. Returning error.")
        return None, "Failed"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get API usage statistics."""
        return {
            "total_requests": self._total_requests,
            "failed_requests": self._failed_requests,
            "providers": [
                {
                    "name": p.name,
                    "enabled": p.enabled,
                    "available": p.is_available(),
                    "successes": p.success_count,
                    "failures": p.failure_count,
                    "last_error": p.last_error
                }
                for p in self.providers
            ]
        }


# Initialize the global LLM Manager
llm_manager = LLMManager()


def init_llm_providers():
    """Initialize and register all LLM providers from configuration."""
    logger.info("=" * 60)
    logger.info("Initializing LLM Providers...")
    logger.info("=" * 60)
    
    # Register Groq
    if GROQ_API_KEY and GROQ_API_KEY != "YOUR_GROQ_API_KEY_HERE":
        llm_manager.register_provider(GroqProvider(GROQ_API_KEY))
    else:
        logger.warning("GROQ_API_KEY not configured. Skipping Groq provider.")
    
    # Register Gemini
    if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE":
        llm_manager.register_provider(GeminiProvider(GEMINI_API_KEY))
    else:
        logger.warning("GEMINI_API_KEY not configured. Skipping Gemini provider.")
    
    # Register Cohere
    if COHERE_API_KEY and COHERE_API_KEY != "YOUR_COHERE_API_KEY_HERE":
        llm_manager.register_provider(CohereProvider(COHERE_API_KEY))
    else:
        logger.warning("COHERE_API_KEY not configured. Skipping Cohere provider.")
    
    available = llm_manager.get_available_providers()
    logger.info(f"Total providers registered: {len(llm_manager.providers)}")
    logger.info(f"Providers available: {len(available)}")
    if available:
        logger.info(f"Active providers: {[p.name for p in available]}")
    else:
        logger.warning("WARNING: No LLM providers are configured! Set your API keys.")
    logger.info("=" * 60)


# ==============================================================================
#  SECTION 5: SYSTEM PROMPT BUILDER
# ==============================================================================

SYSTEM_PROMPT_TEMPLATE = """You are "{bot_name}", a professional, friendly, and highly knowledgeable Property Consultant for "{company_name}".

YOUR ROLE:
- Help users find their ideal property in Scotland.
- You have access to an exclusive property database (provided below).
- Your goal is to understand the user's budget and preferred location, then recommend EXACTLY ONE property from the list that best matches their needs.
- If the user hasn't shared their budget or location yet, politely ask for this information before making a recommendation.

AVAILABLE PROPERTIES:
{properties}

CONVERSATION GUIDELINES:
1. Always greet the user warmly on their first message.
2. Ask for their budget range and preferred location/area in Scotland.
3. Once you have both pieces of information (or enough context), recommend EXACTLY ONE property from the list above.
4. When recommending a property, include:
   - The property title and ID
   - The exact price
   - The location
   - Key features
   - A brief, compelling reason why it matches their needs
5. Keep responses concise but informative (under 200 words).
6. Be professional yet approachable - use a warm Scottish welcome tone.
7. If no property matches well, recommend the closest option and explain why.
8. End responses with a call-to-action like "Would you like to schedule a viewing?" or "Shall I provide more details?"

COMPANY INFO:
- Company: {company_name}
- Tagline: {company_tagline}
- You can arrange viewings, provide mortgage advice referrals, and answer questions about the Scottish property market.

IMPORTANT: Only recommend properties from the list provided. Do not invent properties. Recommend exactly one property at a time.
"""


def build_system_prompt() -> str:
    """Build the full system prompt with current property data."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        bot_name=BOT_NAME,
        company_name=COMPANY_NAME,
        company_tagline=COMPANY_TAGLINE,
        properties=get_all_properties_text()
    )


# ==============================================================================
#  SECTION 6: BUDGET DETECTION & CRM LEAD QUALIFICATION
# ==============================================================================

def detect_budget(text: str) -> Optional[int]:
    """
    Detect budget amount from user message using regex patterns.
    Returns the budget as an integer (in GBP), or None if no budget detected.
    Handles formats like: £250,000, 300k, 250000, 300 thousand
    """
    text_lower = text.lower().replace(",", "")
    
    for pattern in BUDGET_REGEX_PATTERNS:
        matches = re.findall(pattern, text_lower)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0] if match else ""
            if not match:
                continue
            
            try:
                value = float(match)
                # Handle 'k' suffix (thousands)
                if "k" in text_lower[text_lower.find(match):text_lower.find(match) + len(match) + 5]:
                    value *= 1000
                # Handle values that look like they're in thousands already (e.g., 300 = 300,000)
                elif value < 1000:
                    value *= 1000
                
                budget = int(value)
                if 50000 <= budget <= 5000000:  # Reasonable property budget range
                    logger.info(f"[Budget Detector] Detected budget: £{budget:,} from text: '{text}'")
                    return budget
            except (ValueError, IndexError):
                continue
    
    return None


def get_crm_alert() -> str:
    """Return the hidden CRM sync alert appended to responses for qualified leads."""
    return "\n\n[SYSTEM ALERT: Lead Qualified 🟢]"


# ==============================================================================
#  SECTION 7: FLASK HEALTH-CHECK SERVER (For Render.com + UptimeRobot)
# ==============================================================================

flask_app = Flask(__name__)


@flask_app.route("/")
def health_check():
    """Root route for UptimeRobot to ping every 5 minutes. Keeps the service alive."""
    llm_stats = llm_manager.get_stats()
    conv_stats = conversation_mgr.get_stats()
    
    status = {
        "status": "Bot is alive!",
        "bot_name": BOT_NAME,
        "company": COMPANY_NAME,
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": int(time.time() - START_TIME),
        "llm_stats": llm_stats,
        "conversation_stats": conv_stats
    }
    return status, 200


@flask_app.route("/stats")
def detailed_stats():
    """Detailed statistics endpoint for monitoring."""
    return {
        "bot": {
            "name": BOT_NAME,
            "company": COMPANY_NAME,
            "version": "2.0.0",
            "start_time": datetime.fromtimestamp(START_TIME).isoformat()
        },
        "llm": llm_manager.get_stats(),
        "conversations": conversation_mgr.get_stats(),
        "config": {
            "rotation_mode": "random" if ENABLE_RANDOM_ROTATION else "round-robin",
            "max_history": MAX_CONVERSATION_HISTORY,
            "conversation_ttl_hours": CONVERSATION_TTL_HOURS
        }
    }, 200


def run_flask_server():
    """Run the Flask server in a separate thread."""
    logger.info(f"[Flask] Starting health-check server on {FLASK_HOST}:{FLASK_PORT}")
    # Use threaded=True and disable reloader to avoid double-start in production
    flask_app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True, use_reloader=False)


# ==============================================================================
#  SECTION 8: TELEGRAM BOT HANDLERS
# ==============================================================================

# Initialize the Telegram bot
try:
    bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="HTML")
    logger.info(f"[Telegram] Bot initialized successfully: {BOT_NAME}")
except Exception as e:
    logger.error(f"[Telegram] Failed to initialize bot: {e}")
    sys.exit(1)


def send_welcome_message(chat_id: int):
    """Send the initial welcome message to a new user."""
    welcome_text = (
        f"🏠 <b>Welcome to {BOT_NAME}!</b>\n\n"
        f"I'm your personal property consultant for <b>{COMPANY_NAME}</b>.\n"
        f"{COMPANY_TAGLINE}\n\n"
        f"To find your perfect Scottish home, I'll need to know:\n"
        f"1️⃣ Your budget (e.g., £250,000 or 300k)\n"
        f"2️⃣ Your preferred location in Scotland\n\n"
        f"What brings you here today?"
    )
    bot.send_message(chat_id, welcome_text)


def handle_user_message(user_id: int, chat_id: int, message_text: str) -> str:
    """
    Core message handler:
    1. Detect budget from message
    2. Build conversation context
    3. Call LLM with system prompt + history
    4. Append CRM alert if budget detected
    5. Store response in history
    """
    logger.info(f"[Message] User {user_id}: '{message_text[:100]}...'")
    
    # Step 1: Budget detection
    detected_budget = detect_budget(message_text)
    
    # Step 2: Add user message to conversation history
    conversation_mgr.add_message(user_id, "user", message_text)
    
    # Step 3: Build messages with system prompt and history
    history = conversation_mgr.get_history(user_id)
    
    # Include budget hint in system prompt if detected
    system_prompt = build_system_prompt()
    if detected_budget:
        system_prompt += f"\n\n[USER BUDGET DETECTED: £{detected_budget:,} - Use this to find the best matching property.]"
    
    # Step 4: Call LLM via the rotation manager
    response, provider_used = llm_manager.generate_response(history, system_prompt)
    
    if response is None:
        logger.error(f"[Error] All LLM providers failed for user {user_id}")
        return (
            "I apologize, but I'm experiencing a temporary issue connecting to my knowledge base. "
            "Please try again in a moment. If the problem persists, contact our team directly!"
        )
    
    logger.info(f"[Response] Provider '{provider_used}' responded for user {user_id}")
    
    # Step 5: Append CRM lead qualification alert if budget was detected
    if detected_budget:
        response += get_crm_alert()
        logger.info(f"[CRM] Lead qualified for user {user_id} with budget £{detected_budget:,}")
    
    # Step 6: Store assistant response in history
    conversation_mgr.add_message(user_id, "assistant", response)
    
    return response


# --- Telegram Bot Command Handlers ---

@bot.message_handler(commands=["start", "help"])
def handle_start(message):
    """Handle /start and /help commands."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Clear previous conversation for fresh start
    conversation_mgr.clear_history(user_id)
    logger.info(f"[Command] /start from user {user_id}")
    
    send_welcome_message(chat_id)


@bot.message_handler(commands=["properties"])
def handle_properties(message):
    """Handle /properties command - show available properties."""
    chat_id = message.chat.id
    
    properties_text = f"🏘 <b>Available Properties at {COMPANY_NAME}:</b>\n\n"
    for prop in PROPERTY_DATABASE:
        properties_text += (
            f"<b>{prop['title']}</b> ({prop['id']})\n"
            f"📍 {prop['location']}\n"
            f"💰 {prop['price_display']} | 🛏 {prop['bedrooms']} bed | 🛁 {prop['bathrooms']} bath\n"
            f"Type: {prop['type']}\n\n"
        )
    
    bot.send_message(chat_id, properties_text)


@bot.message_handler(commands=["reset"])
def handle_reset(message):
    """Handle /reset command - clear conversation history."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    conversation_mgr.clear_history(user_id)
    logger.info(f"[Command] /reset from user {user_id}")
    
    bot.send_message(
        chat_id,
        "🔄 <b>Conversation reset!</b>\n\n"
        "I've cleared our chat history. Let's start fresh! What are you looking for?"
    )


@bot.message_handler(commands=["status"])
def handle_status(message):
    """Handle /status command - show bot status."""
    chat_id = message.chat.id
    
    llm_stats = llm_manager.get_stats()
    conv_stats = conversation_mgr.get_stats()
    
    active_providers = [p["name"] for p in llm_stats["providers"] if p["available"]]
    
    status_text = (
        f"📊 <b>{BOT_NAME} Status</b>\n\n"
        f"✅ Bot: Online\n"
        f"🏢 Company: {COMPANY_NAME}\n"
        f"🤖 Active LLM Providers: {', '.join(active_providers) if active_providers else 'None'}\n"
        f"📡 Total API Requests: {llm_stats['total_requests']}\n"
        f"❌ Failed Requests: {llm_stats['failed_requests']}\n"
        f"💬 Active Conversations: {conv_stats['active_conversations']}\n"
        f"🔄 Rotation Mode: {'Random' if ENABLE_RANDOM_ROTATION else 'Round-Robin'}"
    )
    
    bot.send_message(chat_id, status_text)


@bot.message_handler(func=lambda message: True, content_types=["text"])
def handle_text_message(message):
    """Handle all text messages from users."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    message_text = message.text.strip()
    
    # Skip commands (handled above)
    if message_text.startswith("/"):
        return
    
    # Send typing indicator
    bot.send_chat_action(chat_id, "typing")
    
    # Process the message
    response = handle_user_message(user_id, chat_id, message_text)
    
    # Send response back to user
    bot.send_message(chat_id, response)


# ==============================================================================
#  SECTION 9: MAIN ENTRY POINT
# ==============================================================================

START_TIME = time.time()


def run_telegram_bot():
    """Run the Telegram bot polling loop."""
    logger.info("[Telegram] Starting bot polling...")
    logger.info("=" * 60)
    logger.info(f"  {BOT_NAME} is now running!")
    logger.info(f"  Company: {COMPANY_NAME}")
    logger.info(f"  Health Check: http://{FLASK_HOST}:{FLASK_PORT}/")
    logger.info("=" * 60)
    
    # Start polling with retry logic
    while True:
        try:
            bot.polling(
                none_stop=True,
                interval=0,
                timeout=20,
                long_polling_timeout=10
            )
        except Exception as e:
            logger.error(f"[Telegram] Polling error: {e}")
            logger.info("[Telegram] Restarting polling in 5 seconds...")
            time.sleep(5)


def main():
    """
    Main entry point:
    1. Initialize LLM providers
    2. Start Flask health-check server in background thread
    3. Start Telegram bot polling in main thread
    """
    print("\n" + "=" * 60)
    print(f"  {BOT_NAME} v2.0.0 - Starting Up...")
    print(f"  {COMPANY_NAME}")
    print("=" * 60 + "\n")
    
    # Initialize LLM providers
    init_llm_providers()
    
    # Verify at least one provider is available
    available = llm_manager.get_available_providers()
    if not available:
        logger.warning("=" * 60)
        logger.warning("WARNING: No LLM API keys are configured!")
        logger.warning("Set GROQ_API_KEY, GEMINI_API_KEY, or COHERE_API_KEY")
        logger.warning("The bot will still run but won't be able to generate AI responses.")
        logger.warning("=" * 60)
    
    # Start Flask server in a background thread
    flask_thread = threading.Thread(
        target=run_flask_server,
        daemon=True,
        name="FlaskServer"
    )
    flask_thread.start()
    logger.info("[Main] Flask health-check server thread started.")
    
    # Give Flask a moment to start
    time.sleep(1)
    
    # Start Telegram bot polling (blocks until interrupted)
    try:
        run_telegram_bot()
    except KeyboardInterrupt:
        logger.info("\n[Main] Shutting down gracefully...")
        logger.info("[Main] Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
