#!/usr/bin/env python3
# main_gold_auto_MM.py - FULL AUTO + MM + 1 POSITION + SL/TP MANAGER
import MetaTrader5 as mt5
import pandas as pd, mplfinance as mpf, time, os, re, sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT_DIR, "data")
CHROME_PROFILE = os.path.join(ROOT_DIR, "chrome_profile_meta")
os.makedirs(BASE, exist_ok=True)
os.makedirs(CHROME_PROFILE, exist_ok=True)

# ================= EDIT DISINI =================
MT5_LOGIN = 60806199
MT5_PASSWORD = "Ur7[fqZ^"
MT5_SERVER = "FinexBisnisSolusi-Demo"
SYMBOL_LIST = ["GOLD", "XAUUSD", "XAUUSD.a", "XAUUSDm", "XAUUSDpro"]

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
                print(f"✅ Symbol: {s}")
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
    # filter hanya magic kita
    return [p for p in positions if p.magic == MAGIC]

def is_max_positions_reached():
    open_pos = get_open_positions()
    count = len(open_pos)
    if count >= MAX_OPEN_POSITIONS:
        print(f"⛔ Sudah ada {count} posisi open (max {MAX_OPEN_POSITIONS}), SKIP new order")
        if count>0:
            for p in open_pos:
                print(f"   -> Ticket {p.ticket} {p.type} {p.volume} Profit {p.profit}")
        return True
    return False

def calculate_lot_by_mm(entry_price, sl_price):
    if not MM_ENABLED:
        return FIXED_LOT
    acc = mt5.account_info()
    if not acc:
        return FIXED_LOT
    balance = acc.balance if USE_BALANCE else acc.equity
    risk_money = balance * (RISK_PERCENT / 100.0)

    sl_distance = abs(entry_price - sl_price)  # dalam dollar GOLD
    if sl_distance < 0.5:
        print(f"⚠️ SL terlalu dekat {sl_distance}, pakai fixed lot")
        return FIXED_LOT

    # Rumus GOLD: 1.00 lot = 100 oz. Jadi $1 gerak = $100
    # risk_money = lot * sl_distance * 100
    # lot = risk_money / (sl_distance * 100)
    lot = risk_money / (sl_distance * 100)

    # sesuaikan dengan step broker
    info = mt5.symbol_info(SYMBOL)
    if info:
        lot = max(info.volume_min, min(info.volume_max, lot))
        # rounding ke step
        step = info.volume_step
        lot = round(lot / step) * step
    lot = max(MIN_LOT, min(MAX_LOT, lot))
    lot = round(lot, 2)
    print(f"💰 MM: Balance {balance} Risk {RISK_PERCENT}% = ${risk_money:.2f} | SL dist ${sl_distance} | Lot hitung {lot}")
    return lot

def manage_existing_positions():
    """Fungsi untuk menyetel SL+TP jika kosong, BE, dan Trailing"""
    positions = get_open_positions()
    if not positions:
        return
    symbol_info = mt5.symbol_info(SYMBOL)
    if not symbol_info:
        return

    for pos in positions:
        ticket = pos.ticket
        # Jika SL/TP kosong (0), set default dari AI terakhir atau 300 points
        if pos.sl == 0 or pos.tp == 0:
            print(f"⚙️ Posisi {ticket} SL/TP kosong, coba set...")
            # ambil dari file answer.txt terakhir
            try:
                with open(os.path.join(BASE, "answer.txt"), "r", encoding="utf-8") as f:
                    txt = f.read()
                m_sl = re.search(r"SL\s*[:=]\s*([\d.]+)", txt, re.I)
                m_tp = re.search(r"TP\s*[:=]\s*([\d.]+)", txt, re.I)
                if m_sl and m_tp:
                    new_sl = float(m_sl.group(1))
                    new_tp = float(m_tp.group(1))
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
        profit_per_001 = pos.profit / (pos.volume / 0.01) if pos.volume>0 else pos.profit
        if profit_per_001 >= AUTO_BE_PROFIT:
            # jika posisi BUY dan SL masih di bawah entry
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
                    print(f"🔒 BE BUY {ticket} SL {pos.sl} -> {new_sl} | {res.retcode}")
            elif pos.type == mt5.POSITION_TYPE_SELL and (pos.sl > pos.price_open or pos.sl==0):
                new_sl = pos.price_open - BE_PLUS_POINTS * symbol_info.point
                if new_sl < pos.sl or pos.sl==0:
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": SYMBOL,
                        "position": ticket,
                        "sl": new_sl,
                        "tp": pos.tp,
                    }
                    res = mt5.order_send(req)
                    print(f"🔒 BE SELL {ticket} SL {pos.sl} -> {new_sl} | {res.retcode}")

        # Trailing Logic
        if profit_per_001 >= TRAIL_START_PROFIT:
            tick = mt5.symbol_info_tick(SYMBOL)
            if not tick:
                continue
            if pos.type == mt5.POSITION_TYPE_BUY:
                new_sl = tick.bid - TRAIL_STEP_POINTS * 5 * symbol_info.point # trail $1.5
                if new_sl > pos.sl + 10*symbol_info.point:
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
                if new_sl < pos.sl - 10*symbol_info.point or pos.sl==0:
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": SYMBOL,
                        "position": ticket,
                        "sl": new_sl,
                        "tp": pos.tp,
                    }
                    mt5.order_send(req)
                    print(f"📉 TRAIL SELL {ticket} SL -> {new_sl}")

# ================== ORIGINAL FUNCTIONS ==================

def make_charts():
    paths=[]
    for name, tf in TIMEFRAMES.items():
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, 120)
        if rates is None or len(rates)==0:
            print(f"❌ {name} no data {mt5.last_error()}"); continue
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={'tick_volume':'volume'}, inplace=True)
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
JAWAB CEPAT FORMAT INI SAJA DI BARIS 1-4:
SIGNAL: BUY/SELL/WAIT
ENTRY: harga
SL: harga
TP: harga
"""
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
    print("⏳ Tunggu Meta AI (max 30s, deteksi cepat)...")
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
            if not txt:
                continue
            if txt == last_text and "SIGNAL:" in txt.upper():
                stable_count += 1
                if stable_count >= 2:
                    answer_text = txt
                    print(f"\n✅ Dapat jawaban cepat!")
                    break
            else:
                stable_count = 0
                last_text = txt
                answer_text = txt
            if "SIGNAL:" in txt.upper() and "SL:" in txt.upper() and "TP:" in txt.upper():
                if stable_count >= 1:
                    answer_text = txt
                    print(f"\n✅ SIGNAL lengkap terdeteksi!")
                    break
            print(".", end="", flush=True)
        except:
            continue
    print("\n=== JAWABAN ===\n", answer_text[:1500])
    open(os.path.join(BASE, "answer.txt"), "w", encoding="utf-8").write(answer_text)
    return answer_text

def execute_order(text):
    m = re.search(r"SIGNAL:\s*(BUY|SELL|WAIT)", text, re.I)
    if not m:
        print("❌ SIGNAL tidak ditemukan")
        return
    signal = m.group(1).upper()
    if signal == "WAIT":
        print("⏸ WAIT - Skip order")
        return

    # --- CEK 1 POSISI ONLY ---
    if is_max_positions_reached():
        return

    def get_val(label):
        r = re.search(rf"{label}\s*[:=]\s*([\d.]+)", text, re.I)
        return float(r.group(1)) if r else None
    sl_raw = get_val("SL")
    tp_raw = get_val("TP")
    entry_ai = get_val("ENTRY")
    if sl_raw is None or tp_raw is None:
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
            print(f"❌ SL/TP terlalu dekat, skip. Price {price_now} SL {sl_raw} TP {tp_raw}")
            return
        if signal == "BUY" and sl_raw >= price_now:
            print(f"❌ SL BUY harus di bawah harga. Price {price_now} SL {sl_raw}")
            return
        if signal == "SELL" and sl_raw <= price_now:
            print(f"❌ SL SELL harus di atas harga. Price {price_now} SL {sl_raw}")
            return

        # --- HITUNG LOT MM ---
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
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        print(f"🚀 KIRIM {signal} @ {price_now} Lot {lot_to_use} (attempt {attempt})")
        res = mt5.order_send(req)
        print(f"Result: {res}")
        if res is None:
            print(f"❌ order_send None: {mt5.last_error()}")
            time.sleep(0.5)
            continue
        if res.retcode in [10008, 10009]:
            print(f"✅ ORDER SUKSES {signal} {price_now} Lot {lot_to_use} Ticket {res.order}")
            open(os.path.join(BASE, "last_order.log"), "a").write(f"{datetime.now()} {signal} SUCCESS Lot{lot_to_use} {res}\n")
            return
        elif res.retcode == 10004:
            print(f"⚠️ Requote, ambil harga baru lagi...")
            time.sleep(0.3)
            continue
        elif res.retcode == 10015:
            print(f"⚠️ Invalid price, retry...")
            time.sleep(0.5)
            continue
        else:
            print(f"❌ Gagal retcode {res.retcode} - {res.comment}")
            if res.retcode in [10016, 10018]:
                break
            time.sleep(0.5)
    print("❌ Semua attempt gagal")

if __name__ == "__main__":
    print("=== FULL AUTO GOLD - MM + 1 POSISI + SL/TP MANAGER ===")
    driver = get_driver()
    print("Jika belum login Meta AI, login di Chrome yang kebuka itu. Setelah login, tekan ENTER disini...")
    input("ENTER untuk mulai cycle...")
    while True:
        try:
            print(f"\n===== CYCLE {datetime.now()} =====")
            # 1. Kelola posisi yang sudah ada dulu (BE + Trailing + Fix SL kosong)
            manage_existing_positions()

            # 2. Kalau sudah max posisi, skip analisa dan tunggu
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
        except KeyboardInterrupt:
            print("Stop manual")
            driver.quit()
            break
        except Exception as e:
            print(f"Loop error {e}")
            import traceback; traceback.print_exc()
            time.sleep(20)
