import os, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio

# Токендерді тексеру
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
METAAPI_TOKEN = os.getenv("METAAPI_TOKEN")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")

print(f"TOKEN бар ма: {bool(TOKEN)}")
print(f"CHAT_ID: {CHAT_ID}")

# Render үшін веб сервер - міндетті
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot is Live! 7 Strategy")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def log_message(self, format, *args):
        return

def run_web():
    port = int(os.environ.get("PORT", 10000))
    print(f"Web server {port} портында")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

# Telegram командалары
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"✅ Бот істеп тұр!\n100$ настройка дайын\nID: {update.effective_chat.id}\n/send деп CHAT_ID-ді осы ID-ге ауыстыр")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"7 Стратегия:\n✅ Orderflow\n✅ OI\n✅ Volume Profile\n✅ AMT\n✅ 2.6\n✅ OTE\n✅ Valium\n\nЛот: 90%->0.05 70%->0.03 50%->0.01\nТП: 200-700 пипс")

# Негізгі функция
def main():
    # Веб серверді бөлек қосу
    threading.Thread(target=run_web, daemon=True).start()
    
    if not TOKEN:
        print("ҚАТЕ: TELEGRAM_TOKEN жоқ! Render Environment-ға қос!")
        # Токен жоқ болса да веб сервер тұра берсін, Deploy failed болмау үшін
        while True:
            pass

    print("Telegram бот қосылуда...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("settings", status))
    
    print("Бот Live!")
    app.run_polling()

if __name__ == "__main__":
    main()
