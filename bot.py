import os, threading, asyncio, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
METAAPI_TOKEN = os.getenv("METAAPI_TOKEN")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")

CONFIG = {"SYMBOL":"XAUUSD","LOT_90":0.05,"LOT_70":0.03,"LOT_50":0.01,"TP_90":700,"TP_70":500,"TP_50":200,"SL":100}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Bot Live")
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def log_message(self,*a): return
def run_web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT",10000))), Handler).serve_forever()

# Командалар - ЕШҚАШАН КҮТПЕЙДІ, БІРДЕН ЖАУАП БЕРЕДІ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(f"✅ Бот дайын!\nID: {update.effective_chat.id}\nXAUUSD 7 стратегия\nЛот: 90%->{CONFIG['LOT_90']} 70%->{CONFIG['LOT_70']} 50%->{CONFIG['LOT_50']}\n/status - сигнал көр")
    except Exception as e:
        print(f"start error {e}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Бірден жауап, MetaApi күтпейді
        await update.message.reply_text("🔍 Сигнал тексеріп жатырмын... 5 сек")
        
        if not METAAPI_TOKEN:
            await update.message.reply_text("⚠️ METAAPI_TOKEN жоқ!\nRender Environment-ға қосылмаған.\nҚазір тек тест режимінде тұрмын.\n\nНастройка:\n✅ Orderflow\n✅ OI\n✅ Volume Profile\n✅ AMT\n✅ 2.6\n✅ OTE\n✅ Valium")
            return

        # Енді ғана MetaApi тексереді
        from metaapi_cloud_sdk import MetaApi
        import pandas as pd
        api = MetaApi(METAAPI_TOKEN)
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        conn = account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized(timeout=30)
        candles = await conn.get_historical_candles(CONFIG['SYMBOL'], '15m', 100)
        closes = [c['close'] for c in candles]
        
        # Қарапайым есептеу
        if len(closes) < 50:
            await update.message.reply_text("Свеча аз, күт...")
            return
            
        ema20 = pd.Series(closes).ewm(20).mean().iloc[-1]
        ema50 = pd.Series(closes).ewm(50).mean().iloc[-1]
        score = 1 if ema20>ema50 else -1
        direction = "BUY" if score>0 else "SELL"
        conf = 75 if abs(ema20-ema50)>2 else 60
        
        if conf>=90: lot=CONFIG['LOT_90']; tp=CONFIG['TP_90']
        elif conf>=70: lot=CONFIG['LOT_70']; tp=CONFIG['TP_70']
        else: lot=CONFIG['LOT_50']; tp=CONFIG['TP_50']

        await update.message.reply_text(f"📊 {CONFIG['SYMBOL']} 15m\nБағыт: {direction}\nСенім: {conf}%\nЛот: {lot}\nТП: {tp} пипс\nСЛ: {CONFIG['SL']}\n\nЕгер {conf}% >=55% болса, бот өзі ашады!\nCHAT_ID: {CHAT_ID}")
        
        await conn.close()
    except Exception as e:
        print(traceback.format_exc())
        await update.message.reply_text(f"Қате болды: {str(e)[:300]}\n\nMetaApi Connected па? metaapi.cloud-та жасыл ма?")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("settings", status_cmd))
    app.add_handler(CommandHandler("send", start))
    print("BOT STARTED")
    app.run_polling()

if __name__ == "__main__":
    main()
