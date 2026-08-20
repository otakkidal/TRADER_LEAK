#!/usr/bin/env python3
# main_gold_auto.py - FULL AUTO NO EA - FIXED FINAL (Path + Fast AI + Anti-Requote)
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
LOT = 0.01
CYCLE_SLEEP = 120  # 120 detik untuk intraday, ganti 60 untuk scalping
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
        print(f"✅ MT5 Connected: {acc.login} {acc.server} Balance {acc.balance}")
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
        order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": LOT,
            "type": order_type,
            "price": price_now,
            "sl": sl_raw,
            "tp": tp_raw,
            "deviation": 50,
            "magic": 202501,
            "comment": f"MetaAI {signal} A{attempt}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        print(f"🚀 KIRIM {signal} @ {price_now} (attempt {attempt})")
        res = mt5.order_send(req)
        print(f"Result: {res}")
        if res is None:
            print(f"❌ order_send None: {mt5.last_error()}")
            time.sleep(0.5)
            continue
        if res.retcode in [10008, 10009]:
            print(f"✅ ORDER SUKSES {signal} {price_now} Ticket {res.order}")
            open(os.path.join(BASE, "last_order.log"), "a").write(f"{datetime.now()} {signal} SUCCESS {res}\n")
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
    print("=== FULL AUTO GOLD - FIXED FINAL ===")
    driver = get_driver()
    print("Jika belum login Meta AI, login di Chrome yang kebuka itu. Setelah login, tekan ENTER disini...")
    input("ENTER untuk mulai cycle...")
    while True:
        try:
            print(f"\n===== CYCLE {datetime.now()} =====")
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
