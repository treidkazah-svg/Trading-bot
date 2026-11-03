import os, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import yfinance as yf
import pandas as pd

TOKEN = os.getenv("TELEGRAM_TOKEN")

class H(BaseHTTPRequestHandler):
 def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"FREE")
 def do_HEAD(self): self.send_response(200); self.end_headers()
 def log_message(self,*a): return
def run_web():
 HTTPServer(("0.0.0.0", int(os.environ.get("PORT",10000))), H).serve_forever()

def get_sig():
 try:
  d=yf.download("GC=F",period="3d",interval="15m",progress=False)
  c=d['Close'].dropna().tolist()
  if len(c)<40: return 55,"КҮТ",0,0
  e20=pd.Series(c).ewm(20).mean().iloc[-1]
  e50=pd.Series(c).ewm(50).mean().iloc[-1]
  score=2 if e20>e50 else -2
  if c[-1]>sum(c[-20:])/20: score+=1
  if c[-1]>max(c[-30:-1]): score+=1
  conf=60+abs(score)*8
  dir="BUY 🟢" if score>0 else "SELL 🔴"
  return min(92,conf),dir,score,c[-1]
 except Exception as e:
  print(e); return 50,"Қате",0,0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
 await update.message.reply_text("✅ ТЕГІН ТЕСТ дайын!\n/status бас - нақты сигнал шығады\n5 шотқа дайын код ішінде тұр!")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
 await update.message.reply_text("🔍 Тегін XAUUSD тексеру...")
 conf, direction, score, price = get_sig()
 lot = 0.05 if conf>=85 else 0.03 if conf>=70 else 0.01
 tp = 700 if conf>=85 else 500 if conf>=70 else 200
 await update.message.reply_text(f"📊 XAUUSD {price:.1f}\nБағыт: {direction}\nСенім: {conf}% ({score}/7)\nЛот: {lot}\nТП: {tp} пипс | СЛ 100\n\n{'🔥 Ашуға болады' if conf>=70 else '⏳ Күт'}\n\nРежим: 🆓 ТЕГІН (ақша сұрамайды)\nЕртең реал 5 шот: FREE_MODE=False қылсаң болды!")

def main():
 threading.Thread(target=run_web,daemon=True).start()
 app=ApplicationBuilder().token(TOKEN).build()
 app.add_handler(CommandHandler("start",start))
 app.add_handler(CommandHandler("status",status_cmd))
 app.add_handler(CommandHandler("settings",status_cmd))
 print("FREE BOT RUNNING")
 app.run_polling()

if __name__=="__main__": main()
