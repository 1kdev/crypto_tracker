# 🚀 Crypto Alert Bot

A simple Telegram bot for cryptocurrency price alerts. The bot uses the public Binance API to fetch real-time market data.

### 🛠 Tech Stack

* Python 3.10+
* aiogram 3.x — an asynchronous framework for working with the Telegram API
* aiosqlite — a library for asynchronous interaction with SQLite
* Binance API — market data retrieval without authentication
* Pydantic-settings & dotenv — configuration and secrets management

### ⚙️ Setup Guide

1. **Clone the repository:**

   ```bash
   git clone https://github.com/1kdev/crypto_tracker.git
   cd crypto_tracker
   ```

2. **Configure environment variables:**
   Create a `.env` file in the project root and add your token:

   ```env
   BOT_TOKEN=your_bot_token_from_BotFather
   ```

3. **Install dependencies:**

   ```bash
   pip install "aiogram<4.0" pydantic-settings python-dotenv aiosqlite
   ```

4. **Run the project:**

   ```bash
   python app.py
   ```

### 📝 Current Features (v1.0.0):

* **New user handling:** Automatically checks and registers a Telegram ID in the database when the `/start` command is used for the first time
* **Interface:** Basic button menu and a foundation for future features
* **Database schema:** Tables created for storing user profiles and their personal ticker lists

### 🚀 Planned Features:

* **Add tickers:** Save user-selected assets to the database via FSM
* **Monitoring:** Display current prices for the user’s selected assets
* **Management:** Ability to remove tickers from tracking
* **Alerts:** Configurable periodic notifications (every 1, 2, or 4 hours)

*Developed by 1kdev*
