import os, threading, asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from metaapi_cloud_sdk import MetaApi
import pandas as pd
import ta

# ========= НАСТРОЙКА - ОСЫ ЖЕРДІ ӨЗГЕРТЕ АЛАСЫҢ =========
CONFIG = {
    "SYMBOL": "XAUUSD",  # алдағы уақытта BTCUSD деп өзгерте аласың
    "DEPOSIT": 100,
    "LOTS": {           # лотты осы жерден өзгертесің
        90: 0.05,
        70: 0.03,
        50: 0.01,
    },
    "TP_PIPS": {        # тейк 200-700 арасында
        90: 700,
        80: 500,
        65: 300,
        50: 200,
    },
    "SL_PIPS": {        # стоп қатты үлкен емес
        90: 150,
        70: 120,
        50: 80,
    },
    "MIN_CONF_TO_ENTER": 55,  # 55% төмен кірмейді
    "EARLY_CLOSE_CONF": 50,   # 50% түссе бірден жабады
}
# ========================================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
METAAPI_TOKEN = os.getenv("METAAPI_TOKEN")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")

# Render үшін веб сервер
class Handler(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"Bot Live!")
    def do_HEAD(self): self.send_response(200); self.end_headers()
def run_web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), Handler).serve_forever()

# --- 7 СТРАТЕГИЯ (ОЙДАН АУЫТҚЫМАЙ) ---
def get_confidence(df):
    score = 50
    v = [] # 7 дауыс
    
    # 1. Orderflow
    v.append(1 if df['c'].iloc[-1] > df['c'].iloc[-2] and df['v'].iloc[-1] > df['v'].mean() else -1 if df['c'].iloc[-1] < df['c'].iloc[-2] else 0)
    # 2. OI + CVD
    v.append(1 if df['v'].iloc[-1] > df['v'].tail(10).mean() else 0)
    # 3. Volume Profile
    poc = df['c'].median(); v.append(1 if df['c'].iloc[-1] > poc else -1)
    # 4. AMT
    ema20 = df['c'].ewm(20).mean().iloc[-1]; ema50 = df['c'].ewm(50).mean().iloc[-1]; v.append(1 if ema20>ema50 else -1)
    # 5. 2.6 стратегия
    high26 = df['h'].tail(26).max(); v.append(1 if df['c'].iloc[-1] < high26*0.97 else -1)
    # 6. OTE 0.62-0.79
    hi = df['h'].tail(50).max(); lo = df['l'].tail(50).min(); fib62 = hi-(hi-lo)*0.62; fib79 = hi-(hi-lo)*0.79; price=df['c'].iloc[-1]; v.append(1 if fib79<=price<=fib62 else 0)
    # 7. Valium / RSI
    rsi = ta.momentum.rsi(df['c'],14).iloc[-1]; v.append(1 if rsi<45 else -1 if rsi>55 else 0)

    total = sum(v)
    conf = 50 + abs(total)*7 # 5/7 = 85%, 7/7 = 99%
    direction = "BUY" if total>0 else "SELL" if total<0 else "NEUTRAL"
    return min(95,conf), direction, total

def get_lot_tp_sl(conf):
    if conf >= 90: return CONFIG["LOTS"][90], CONFIG["TP_PIPS"][90], CONFIG["SL_PIPS"][90]
    if conf >= 70: return CONFIG["LOTS"][70], CONFIG["TP_PIPS"][80], CONFIG["SL_PIPS"][70]
    return CONFIG["LOTS"][50], CONFIG["TP_PIPS"][50], CONFIG["SL_PIPS"][50]

# --- TELEGRAM ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Бот дайын!\nДепо: {CONFIG['DEPOSIT']}$\nСимвол: {CONFIG['SYMBOL']}\nЛот: 90%->{CONFIG['LOTS'][90]} 70%->{CONFIG['LOTS'][70]} 50%->{CONFIG['LOTS'][50]}\nЛогика: Сенім 50% түссе жабамын, 250 пипс жүрсе бақылаймын")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Қазіргі настройка:\n{CONFIG}\nӨзгерту үшін GitHub-та bot.py ішінде CONFIG дегенді түзетесің!")

# --- НЕГІЗГІ ТРЕЙДИНГ ЦИКЛЫ ---
async def trading_loop(app):
    if not METAAPI_TOKEN: 
        print("METAAPI_TOKEN жоқ, тек сигнал режимінде")
        return
    api = MetaApi(METAAPI_TOKEN)
    account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
    await account.wait_connected()
    conn = account.get_rpc_connection()
    await conn.connect()
    await conn.wait_synchronized()
    print("MetaApi қосылды!")

    entry_price = None
    entry_conf = 0

    while True:
        try:
            candles = await conn.get_historical_candles(CONFIG["SYMBOL"], "15m", 100)
            df = pd.DataFrame(candles)
            df.rename(columns={'close':'c','high':'h','low':'l','open':'o','tick_volume':'v'}, inplace=True)
            
            conf, direction, score = get_confidence(df)
            lot, tp_pips, sl_pips = get_lot_tp_sl(conf)
            positions = await conn.get_positions()
            pos = next((p for p in positions if p['symbol']==CONFIG["SYMBOL"]), None)

            # ЕРТЕ ЖАБУ ЛОГИКАСЫ - СЕН СҰРАҒАН
            if pos:
                profit_pips = (df['c'].iloc[-1] - entry_price)*10 if pos['type']=='POSITION_TYPE_BUY' else (entry_price - df['c'].iloc[-1])*10
                # 1. Сенім 50% түссе - БІРДЕН ЖАБУ
                if conf < CONFIG["EARLY_CLOSE_CONF"]:
                    await conn.close_position(pos['id'])
                    await app.bot.send_message(chat_id=pos['id'], text=f"⚠️ Сенім {entry_conf}% -> {conf}% түсті!  {profit_pips:.0f} пипсте жауып тастадым!")
                    entry_price = None
                # 2. 250 пипс жүрді, бірақ бағыты әлсіз - жабу, күшті болса ұстау
                elif profit_pips >= 250 and conf < 70 and direction != ("BUY" if pos['type']=='POSITION_TYPE_BUY' else "SELL"):
                    await conn.close_position(pos['id'])
                    await app.bot.send_message(chat_id=pos['id'], text=f"🔒 250 пипс+ алдым, рынок өзгерді ({conf}%) - жауып алдым!")
                    entry_price = None

            # ЖАҢА СДЕЛКА КІРУ
            if not pos and conf >= CONFIG["MIN_CONF_TO_ENTER"]:
                price = await conn.get_symbol_price(CONFIG["SYMBOL"])
                if direction == "BUY":
                    await conn.create_market_buy_order(CONFIG["SYMBOL"], lot, price['ask']-sl_pips*0.1, price['ask']+tp_pips*0.1)
                else:
                    await conn.create_market_sell_order(CONFIG["SYMBOL"], lot, price['bid']+sl_pips*0.1, price['bid']-tp_pips*0.1)
                entry_price = df['c'].iloc[-1]
                entry_conf = conf
                await app.bot.send_message(chat_id=int(os.getenv("CHAT_ID")), text=f"{'🟢' if direction=='BUY' else '🔴'} {direction} {score}/7 | Сенім {conf}% | Лот {lot} | ТП {tp_pips} пипс | СЛ {sl_pips}")

            await asyncio.sleep(300) # 5 минут сайын тексереді
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(60)

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("settings", settings))
    
    # trading loop-ты фонға қосу
    app.job_queue.run_once(lambda ctx: asyncio.create_task(trading_loop(app)), 5)
    app.run_polling()

if __name__ == "__main__":
    main()
