import os, threading, asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import pandas as pd

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
METAAPI_TOKEN = os.getenv("METAAPI_TOKEN")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")

# ====== СЕН ӨЗГЕРТЕ АЛАТЫН НАСТРОЙКА ======
CONFIG = {
    "SYMBOL": "XAUUSD",
    "LOT_90": 0.05,
    "LOT_70": 0.03,
    "LOT_50": 0.01,
    "TP_90": 700,
    "TP_70": 500,
    "TP_50": 200,
    "SL": 100, # стоп үлкен емес
}
# =========================================

class Handler(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Bot Live 7 Strategy")
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def log_message(self, *a): return
def run_web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), Handler).serve_forever()

# 7 СТРАТЕГИЯНЫ ЕСЕПТЕУ
def calculate_confidence(candles):
    # candles - MetaApi-дан келген
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    vols = [c.get('tick_volume', 1) for c in candles]
    
    votes = []
    # 1 Orderflow
    votes.append(1 if closes[-1] > closes[-2] and vols[-1] > sum(vols[-10:])/10 else -1 if closes[-1] < closes[-2] else 0)
    # 2 OI
    votes.append(1 if vols[-1] > sum(vols[-5:])/5 else 0)
    # 3 Volume Profile
    poc = sum(closes)/len(closes); votes.append(1 if closes[-1] > poc else -1)
    # 4 AMT
    ema20 = pd.Series(closes).ewm(20).mean().iloc[-1]; ema50 = pd.Series(closes).ewm(50).mean().iloc[-1]; votes.append(1 if ema20>ema50 else -1)
    # 5 2.6
    high26 = max(highs[-26:]); votes.append(-1 if closes[-1] > high26*0.97 else 1)
    # 6 OTE
    hi = max(highs[-50:]); lo = min(lows[-50:]); fib62 = hi-(hi-lo)*0.62; fib79 = hi-(hi-lo)*0.79; votes.append(1 if fib79 <= closes[-1] <= fib62 else 0)
    # 7 Valium RSI
    delta = pd.Series(closes).diff(); gain = delta.where(delta>0,0).rolling(14).mean(); loss = -delta.where(delta<0,0).rolling(14).mean(); rs = gain/loss; rsi = 100-(100/(1+rs)); rsi_val = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
    votes.append(1 if rsi_val<45 else -1 if rsi_val>55 else 0)
    
    score = sum(votes)
    conf = 50 + abs(score)*7  # 5 дауыс = 85%, 7 дауыс = 99%
    direction = "BUY" if score>0 else "SELL" if score<0 else "NEUTRAL"
    return min(95,int(conf)), direction, score, votes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"✅ 7 Стратегия Live!\n{CONFIG['SYMBOL']}\nЛот: 90%->{CONFIG['LOT_90']} 70%->{CONFIG['LOT_70']} 50%->{CONFIG['LOT_50']}\nТП: {CONFIG['TP_90']}/{CONFIG['TP_70']}/{CONFIG['TP_50']} пипс\nСЛ: {CONFIG['SL']}\n\nКомандалар:\n/status - қазіргі сигнал\n/settings - настройка")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not METAAPI_TOKEN:
            await update.message.reply_text("METAAPI_TOKEN қосылмаған, тек тест режимінде тұрмын")
            return
        from metaapi_cloud_sdk import MetaApi
        api = MetaApi(METAAPI_TOKEN)
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        conn = account.get_rpc_connection()
        await conn.connect(); await conn.wait_synchronized()
        candles = await conn.get_historical_candles(CONFIG['SYMBOL'], '15m', 100)
        conf, direction, score, votes = calculate_confidence(candles)
        await update.message.reply_text(f"📊 {CONFIG['SYMBOL']}\nДауыс: {votes}\nScore: {score}/7\nСенім: {conf}%\nБағыт: {direction}\nЛот: {CONFIG['LOT_90'] if conf>=90 else CONFIG['LOT_70'] if conf>=70 else CONFIG['LOT_50']}")
    except Exception as e:
        await update.message.reply_text(f"Қате: {e}")

async def trading_loop(app):
    if not METAAPI_TOKEN or not ACCOUNT_ID:
        print("MetaApi жоқ, тек сигнал күтуде")
        return
    try:
        from metaapi_cloud_sdk import MetaApi
        api = MetaApi(METAAPI_TOKEN)
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        if account.state != 'DEPLOYED': await account.deploy()
        await account.wait_connected()
        conn = account.get_rpc_connection()
        await conn.connect(); await conn.wait_synchronized()
        print("MetaApi қосылды!")
        
        entry_price = None; entry_conf = 0
        while True:
            try:
                candles = await conn.get_historical_candles(CONFIG['SYMBOL'], '15m', 100)
                if not candles: await asyncio.sleep(10); continue
                conf, direction, score, votes = calculate_confidence(candles)
                
                # лот/тп таңдау
                if conf >= 90: lot = CONFIG['LOT_90']; tp = CONFIG['TP_90']
                elif conf >= 70: lot = CONFIG['LOT_70']; tp = CONFIG['TP_70']
                else: lot = CONFIG['LOT_50']; tp = CONFIG['TP_50']
                sl = CONFIG['SL']

                positions = await conn.get_positions()
                pos = next((p for p in positions if p['symbol']==CONFIG['SYMBOL']), None)

                if pos:
                    curr_price = candles[-1]['close']
                    profit_pips = (curr_price - entry_price)*10 if pos['type']=='POSITION_TYPE_BUY' else (entry_price - curr_price)*10 if entry_price else 0
                    
                    # ЕРТЕ ЖАБУ: сенім 50 түссе
                    if conf < 50:
                        await conn.close_position(pos['id'])
                        await app.bot.send_message(chat_id=int(CHAT_ID), text=f"⚠️ Сенім {entry_conf}% -> {conf}% түсті! {profit_pips:.0f} пипсте ЖАУЫП ТАСТАДЫМ!")
                        entry_price = None
                    # 250 пипс жүрді бірақ рынок өзгерді
                    elif profit_pips >= 250 and conf < 70:
                        await conn.close_position(pos['id'])
                        await app.bot.send_message(chat_id=int(CHAT_ID), text=f"🔒 250+ пипс алдым ({profit_pips:.0f}), рынок өзгерді ({conf}%) - жауып алдым!")
                        entry_price = None
                else:
                    if conf >= 55 and direction != "NEUTRAL":
                        price = await conn.get_symbol_price(CONFIG['SYMBOL'])
                        if direction == "BUY":
                            await conn.create_market_buy_order(CONFIG['SYMBOL'], lot, price['ask']-sl*0.1, price['ask']+tp*0.1)
                        else:
                            await conn.create_market_sell_order(CONFIG['SYMBOL'], lot, price['bid']+sl*0.1, price['bid']-tp*0.1)
                        entry_price = candles[-1]['close']; entry_conf = conf
                        await app.bot.send_message(chat_id=int(CHAT_ID), text=f"{'🟢' if direction=='BUY' else '🔴'} {direction} {score}/7 Сенім {conf}% | Лот {lot} | ТП {tp} пипс | СЛ {sl} | Дауыс {votes}")

                await asyncio.sleep(300) # 5 минут
            except Exception as e:
                print(f"Loop error: {e}"); await asyncio.sleep(60)
    except Exception as e:
        print(f"Trading loop fatal: {e}")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("settings", status_cmd))
    
    # trading loop-ты фонға қосу
    async def on_startup(app):
        asyncio.create_task(trading_loop(app))
    app.post_init = on_startup
    
    app.run_polling()

if __name__ == "__main__":
    main()
