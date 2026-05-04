# AlpacaTGbot
.. just an API test trading Autobot

_______________________________

cd ~/utbot
source venv/bin/activate
pip freeze > requirements.txt

_______________________________
.env
_______________________________

APCA_API_KEY_ID=your_paper_key
APCA_API_SECRET_KEY=your_paper_secret
APCA_API_BASE_URL=https://paper-api.alpaca.markets
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
_______________________________

/home/yourusername/alpaca-bot/
├── venv/                 # Virtual environment (already there)
├── .env                  # API keys (already there)
├── Alpaca_Autobot.py     # ← PUT THE BOT HERE
├── trading_bot.log       # Will be created when you run
└── requirements.txt      # Optional: list of packages
