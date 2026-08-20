import MetaTrader5 as mt5
import pandas as pd
import mplfinance as mpf
import time
import os
import re
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

# Load variabel dari file .env
load_dotenv()

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT_DIR, "data")
CHROME_PROFILE = os.path.join(ROOT_DIR, "chrome_profile_meta")
os.makedirs(BASE, exist_ok=True)
os.makedirs(CHROME_PROFILE, exist_ok=True)

# ================= KREDENSIAL DARI .ENV =================
MT5_LOGIN = int(os.getenv("MT5_LOGIN", 0))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
SYMBOL_LIST = ["GOLD", "XAUUSD", "XAUUSD.a", "XAUUSDm", "XAUUSDpro"]

# ================= EDIT DISINI =================
# --- MONEY MANAGEMENT ---
MM_ENABLED = True
RISK_PERCENT = 1.0        # risiko per trade 1% dari balance
MAX_LOT = 0.20
MIN_LOT = 0.01
FIXED_LOT = 0.01          # fallback jika MM off
USE_BALANCE = True        # True = pakai balance, False = pakai equity

# --- TRADE CONTROL ---
MAX_OPEN_POSITIONS = 1    # BATASI HANYA 1 TRANSAKSI
MAGIC = 202501

# --- SL TP MANAGER ---
AUTO_BE_PROFIT = 150      # $ profit per 0.01 lot -> pindah SL ke BE+2$
BE_PLUS_POINTS = 200      # 200 points = $2 untuk GOLD
TRAIL_START_PROFIT = 300  # mulai trailing setelah profit $3 per 0.01 lot
TRAIL_STEP_POINTS = 150   # trail setiap $1.5

CYCLE_SLEEP = 120
# ===============================================

TIMEFRAMES = {
    "H1": mt5.TIMEFRAME_H1,
    "M30": mt5.TIMEFRAME_M30,
    "M15": mt5.TIMEFRAME_M15,
    "M5": mt5.TIMEFRAME_M5,
    "M1": mt5.TIMEFRAME_M1,
}

def init_mt5():
    if not MT5_LOGIN or not MT5_PASSWORD:
        print("❌ Kredensial tidak ditemukan di file .env")
        return None
        
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print(f"Try without login... {mt5.last_error()}")
        if not mt5.initialize():
            return None
            
    acc = mt5.account_info()
    if acc:
        print(f"✅ MT5 Connected: {acc.login} {acc.server} Balance {acc.balance} Equity {acc.equity}")
    for s in SYMBOL_LIST:
        if mt5.symbol_select(s, True):
            info = mt5.symbol_info(s)
            if info:
                print(f"✅ Symbol Terdeteksi: {s}")
                return s
    return SYMBOL_LIST[0]

SYMBOL = init_mt5()
if not SYMBOL:
    print("❌ Gagal init MT5")
    sys.exit(1)

# ================== MM & POSITION CHECK ==================

def get_open_positions():
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return [p for p in positions if p.magic == MAGIC]

def is_max_positions_reached():
    open_pos = get_open_positions()
    count = len(open_pos)
    if count >= MAX_OPEN_POSITIONS:
        print(f"⛔ Sudah ada {count} posisi open (max {MAX_OPEN_POSITIONS}), SKIP new order")
        for p in open_pos:
            print(f"   -> Ticket {p.ticket} {p.type} {p.volume} Profit {p.profit}")
        return True
    return False

def calculate_lot_by_mm(entry_price, sl_price):
    if not MM_ENABLED:
        return FIXED_LOT
        
    acc = mt5.account_info()
    info = mt5.symbol_info(SYMBOL)
    if not acc or not info:
        return FIXED_LOT
        
    balance = acc.balance if USE_BALANCE else acc.equity
    risk_money = balance * (RISK_PERCENT / 100.0)
    sl_distance = abs(entry_price - sl_price)
    
    if sl_distance < 0.5:
        print(f"⚠️ SL terlalu dekat {sl_distance}, pakai fixed lot")
        return FIXED_LOT

    # Gunakan Contract Size asli (Bukan di-hardcode 100)
    contract_size = info.trade_contract_size
    lot = risk_money / (sl_distance * contract_size)
    
    # Sesuaikan dengan batasan broker
    lot = max(info.volume_min, min(info.volume_max, lot))
    step = info.volume_step
    lot = round(lot / step) * step
    lot = max(MIN_LOT, min(MAX_LOT, lot))
    
    print(f"💰 MM: Balance {balance} Risk {RISK_PERCENT}% = ${risk_money:.2f} | SL dist ${sl_distance} | Lot {round(lot, 2)}")
    return round(lot, 2)

def manage_existing_positions():
    positions = get_open_positions()
    if not positions:
        return
        
    symbol_info = mt5.symbol_info(SYMBOL)
    if not symbol_info:
        return

    for pos in positions:
        ticket = pos.ticket
        
        # Perbaiki Jika SL/TP kosong berdasarkan file answer JSON terakhir
        if pos.sl == 0 or pos.tp == 0:
            print(f"⚙️ Posisi {ticket} SL/TP kosong, mencoba recover dari answer.txt...")
            try:
                with open(os.path.join(BASE, "answer.txt"), "r", encoding="utf-8") as f:
                    txt = f.read()
                json_match = re.search(r'\{.*?\}', txt, re.DOTALL)
                if json_match:
                    ai_data = json.loads(json_match.group(0))
                    new_sl = float(ai_data.get("SL", 0))
                    new_tp = float(ai_data.get("TP", 0))
                    
                    if new_sl > 0 and new_tp > 0:
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": SYMBOL,
                            "position": ticket,
                            "sl": new_sl,
                            "tp": new_tp,
                        }
                        res = mt5.order_send(req)
                        print(f"  Set SLTP {ticket} -> {res}")
            except Exception as e:
                print(f"  Gagal set SLTP kosong: {e}")

        # Break Even Logic
        profit_per_001 = pos.profit / (pos.volume / 0.01) if pos.volume > 0 else pos.profit
        if profit_per_001 >= AUTO_BE_PROFIT:
            if pos.type == mt5.POSITION_TYPE_BUY and pos.sl < pos.price_open:
                new_sl = pos.price_open + BE_PLUS_POINTS * symbol_info.point
                if new_sl > pos.sl:
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": SYMBOL,
                        "position": ticket,
                        "sl": new_sl,
                        "tp": pos.tp,
                    }
                    res = mt5.order_send(req)
                    print(f"🔒 BE BUY {ticket} SL {pos.sl} -> {new_sl} | {res.retcode if res else 'Fail'}")
                    
            elif pos.type == mt5.POSITION_TYPE_SELL and (pos.sl > pos.price_open or pos.sl == 0):
                new_sl = pos.price_open - BE_PLUS_POINTS * symbol_info.point
                if new_sl < pos.sl or pos.sl == 0:
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": SYMBOL,
                        "position": ticket,
                        "sl": new_sl,
                        "tp": pos.tp,
                    }
                    res = mt5.order_send(req)
                    print(f"🔒 BE SELL {ticket} SL {pos.sl} -> {new_sl} | {res.retcode if res else 'Fail'}")

        # Trailing Logic
        if profit_per_001 >= TRAIL_START_PROFIT:
            tick = mt5.symbol_info_tick(SYMBOL)
            if not tick:
                continue
            if pos.type == mt5.POSITION_TYPE_BUY:
                new_sl = tick.bid - TRAIL_STEP_POINTS * 5 * symbol_info.point
                if new_sl > pos.sl + 10 * symbol_info.point:
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": SYMBOL,
                        "position": ticket,
                        "sl": new_sl,
                        "tp": pos.tp,
                    }
                    mt5.order_send(req)
                    print(f"📈 TRAIL BUY {ticket} SL -> {new_sl}")
            else:
                new_sl = tick.ask + TRAIL_STEP_POINTS * 5 * symbol_info.point
                if new_sl < pos.sl - 10 * symbol_info.point or pos.sl == 0:
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": SYMBOL,
                        "position": ticket,
                        "sl": new_sl,
                        "tp": pos.tp,
                    }
                    mt5.order_send(req)
                    print(f"📉 TRAIL SELL {ticket} SL -> {new_sl}")

# ================== AI VISUAL FUNCTIONS ==================

def make_charts():
    paths = []
    for name, tf in TIMEFRAMES.items():
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, 120)
        if rates is None or len(rates) == 0:
            print(f"❌ {name} no data {mt5.last_error()}"); continue
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={'tick_volume': 'volume'}, inplace=True)
        png = os.path.join(BASE, f"gold_chart_{name}.png")
        try:
            mc = mpf.make_marketcolors(up='#26a69a', down='#ef5350', wick='inherit', volume='in')
            s = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='yahoo', gridstyle='--', y_on_right=True)
            mpf.plot(df.tail(80), type='candle', style=s,
                     title=f"{SYMBOL} {name} {datetime.now().strftime('%H:%M:%S')}",
                     ylabel='Price', volume=True, figsize=(12,5),
                     savefig=dict(fname=png, dpi=120, bbox_inches='tight'))
            paths.append(png)
            print(f"✅ {name} {png}")
        except Exception as e:
            print(f"Chart {name} error {e}")
    return paths

def get_driver():
    import chromedriver_autoinstaller
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    chromedriver_autoinstaller.install()
    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument(f"--user-data-dir={CHROME_PROFILE}")
    opts.add_experimental_option("detach", True)
    opts.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=opts)
    driver.get("https://www.meta.ai/")
    return driver

def ask_meta_ai(driver, image_paths):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys
    wait = WebDriverWait(driver, 10)
    
    if "meta.ai" not in driver.current_url:
        driver.get("https://www.meta.ai/")
        
    prompt = f"""GOLD {SYMBOL} H1 M30 M15 M5 M1. Analisa SMC OB+FVG+Liquidity.
JAWAB HANYA DENGAN FORMAT JSON VALID INI TANPA TEKS LAIN:
{{
  "SIGNAL": "BUY",
  "ENTRY": 2000.50,
  "SL": 1995.00,
  "TP": 2010.00
}}"""

    for p in image_paths:
        try:
            file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            file_input.send_keys(p)
            print(f"Upload {os.path.basename(p)}")
            time.sleep(1.2)
        except:
            pass
            
    try:
        box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div[contenteditable='true']")))
        box.click()
        time.sleep(0.3)
        box.send_keys(prompt)
        time.sleep(0.3)
        box.send_keys(Keys.RETURN)
    except Exception as e:
        print(f"Box error {e}")
        return ""
        
    print("⏳ Tunggu Meta AI menjawab JSON (max 30s)...")
    answer_text = ""
    stable_count = 0
    last_text = ""
    for _ in range(35):
        time.sleep(0.8)
        try:
            bubbles = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant'], div.prose")
            if not bubbles:
                print(".", end="", flush=True)
                continue
            txt = bubbles[-1].text.strip()
            if not txt: continue
            
            # Cari apakah AI sudah mulai membentuk JSON
            if txt == last_text and ("{" in txt and "}" in txt):
                stable_count += 1
                if stable_count >= 2:
                    answer_text = txt
                    print(f"\n✅ JSON stabil terdeteksi!")
                    break
            else:
                stable_count = 0
                last_text = txt
                answer_text = txt
            print(".", end="", flush=True)
        except:
            continue
            
    print("\n=== JAWABAN MENTAH ===\n", answer_text)
    open(os.path.join(BASE, "answer.txt"), "w", encoding="utf-8").write(answer_text)
    return answer_text

def execute_order(text):
    # Ekstraksi JSON
    json_match = re.search(r'\{.*?\}', text, re.DOTALL)
    if not json_match:
        print("❌ Gagal menemukan format JSON dari jawaban AI.")
        return

    try:
        ai_data = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        print("❌ JSON dari AI tidak valid / rusak.")
        return

    signal = ai_data.get("SIGNAL", "").upper()
    if signal == "WAIT" or signal not in ["BUY", "SELL"]:
        print(f"⏸ Sinyal '{signal}' - Skip order")
        return

    if is_max_positions_reached():
        return

    entry_ai = float(ai_data.get("ENTRY", 0))
    sl_raw = float(ai_data.get("SL", 0))
    tp_raw = float(ai_data.get("TP", 0))

    if sl_raw == 0 or tp_raw == 0:
        print(f"❌ SL/TP tidak lengkap SL={sl_raw} TP={tp_raw}, skip")
        return
        
    print(f"🤖 AI Signal: {signal} ENTRY AI {entry_ai} SL {sl_raw} TP {tp_raw}")

    for attempt in range(1, 4):
        tick = mt5.symbol_info_tick(SYMBOL)
        if not tick:
            print(f"❌ Tick tidak ada attempt {attempt}")
            time.sleep(0.5)
            continue
            
        price_now = tick.ask if signal == "BUY" else tick.bid
        spread = tick.ask - tick.bid
        print(f"Attempt {attempt}/3 | Price Now {price_now} Spread {spread:.2f} | SL {sl_raw} TP {tp_raw}")

        if abs(price_now - sl_raw) < 1.0 or abs(tp_raw - price_now) < 1.0:
            print(f"❌ SL/TP terlalu dekat, skip.")
            return
        if signal == "BUY" and sl_raw >= price_now:
            print(f"❌ SL BUY harus di bawah harga.")
            return
        if signal == "SELL" and sl_raw <= price_now:
            print(f"❌ SL SELL harus di atas harga.")
            return

        lot_to_use = calculate_lot_by_mm(price_now, sl_raw)
        order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
        
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": lot_to_use,
            "type": order_type,
            "price": price_now,
            "sl": sl_raw,
            "tp": tp_raw,
            "deviation": 50,
            "magic": MAGIC,
            "comment": f"MetaAI {signal} MM{RISK_PERCENT}%",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC, # Ganti ke ORDER_FILLING_FOK jika broker menolak
        }
        
        print(f"🚀 KIRIM {signal} @ {price_now} Lot {lot_to_use} (attempt {attempt})")
        res = mt5.order_send(req)
        
        if res is None:
            print(f"❌ order_send None: {mt5.last_error()}")
            time.sleep(0.5)
            continue
            
        if res.retcode in [10008, 10009]:
            print(f"✅ ORDER SUKSES {signal} {price_now} Lot {lot_to_use} Ticket {res.order}")
            open(os.path.join(BASE, "last_order.log"), "a").write(f"{datetime.now()} {signal} SUCCESS Lot{lot_to_use} {res}\n")
            return
        elif res.retcode in [10004, 10015]:
            print(f"⚠️ Requote/Invalid price, ambil harga baru...")
            time.sleep(0.5)
            continue
        else:
            print(f"❌ Gagal retcode {res.retcode} - {res.comment}")
            if res.retcode in [10016, 10018]:
                break
            time.sleep(0.5)
            
    print("❌ Semua attempt order gagal")

if __name__ == "__main__":
    print("=== FULL AUTO GOLD - MM + 1 POSISI + SL/TP MANAGER (JSON SAFE) ===")
    driver = get_driver()
    print("Jika belum login Meta AI, login di Chrome yang kebuka itu. Setelah login, tekan ENTER disini...")
    input("ENTER untuk mulai cycle...")
    
    try:
        while True:
            try:
                print(f"\n===== CYCLE {datetime.now()} =====")
                # 1. Kelola posisi
                manage_existing_positions()

                # 2. Kalau sudah max posisi, skip analisa
                if is_max_positions_reached():
                    print(f"💤 Ada posisi open, sleep {CYCLE_SLEEP}s sambil trailing...")
                    time.sleep(CYCLE_SLEEP)
                    continue

                pngs = make_charts()
                if len(pngs) < 3:
                    print("Chart kurang, retry 15s")
                    time.sleep(15)
                    continue
                    
                answer = ask_meta_ai(driver, pngs)
                execute_order(answer)
                
                print(f"Sleep {CYCLE_SLEEP} detik...")
                time.sleep(CYCLE_SLEEP)
                
            except Exception as e:
                print(f"Loop error {e}")
                import traceback; traceback.print_exc()
                time.sleep(20)
                
    except KeyboardInterrupt:
        print("\n🛑 Dihentikan secara manual...")
    finally:
        print("Menutup Chrome dan MT5 Connection...")
        driver.quit()
        mt5.shutdown()
        print("Selesai.")