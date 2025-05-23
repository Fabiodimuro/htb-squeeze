
#!/usr/bin/env python3
"""Hard-to-Borrow squeeze monitor – Render worker con yfinance"""

import os, time, requests, datetime, logging
from math import isclose
import yfinance as yf

TICKERS = [
    'RGC','LUCY','PONY','BDMD','MRNO',
    'TIVC','OMH','BRLS','NIVF','UP',
    'HNRA','DUO','CXAI','LOCL','LUNR',
    'ENSC','SAI','GCT','GDC','APLM',
    'SPRC','HCWB','PEGY','NOGN','AMDX',
    'TNYA','SERA','PXLW','AKAN','INPX'
]

FINTEL = os.getenv('FINTEL_KEY')
TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT  = os.getenv('TG_CHAT')
API_TG   = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.INFO)

PDH_CACHE = {}

def pdh(tic):
    if tic in PDH_CACHE and (datetime.datetime.utcnow()-PDH_CACHE[tic]['ts']).seconds < 3600:
        return PDH_CACHE[tic]['h']
    stock = yf.Ticker(tic)
    hist = stock.history(period='2d')
    if len(hist) < 2:
        raise ValueError('no previous day')
    h = hist.iloc[-2]['High']
    PDH_CACHE[tic] = {'h': h, 'ts': datetime.datetime.utcnow()}
    return h

def quote(tic):
    stock = yf.Ticker(tic)
    data = stock.history(period="1d", interval="1m")
    if data.empty:
        raise ValueError("no data")
    price = data["Close"].iloc[-1]
    vol = data["Volume"].sum()
    return float(price), int(vol)

def borrow_data(tic):
    try:
        r = requests.get(f'https://fintel.io/api/ss/us/{tic}?token={FINTEL}',
                         headers={'User-Agent': 'HTB-Screener/1.0'}, timeout=10)
        if not r.ok:
            raise ValueError(f"HTTP error {r.status_code}")
        j = r.json()
        if 'data' not in j or not j['data']:
            raise ValueError("no borrow data")
        return float(j['data'][0]['fee']) * 100, int(j['data'][0]['available'])
    except Exception as e:
        logging.error(f"borrow_data {tic}: {e}")
        return 0, 999999  # fallback: fee basso e availability alta, quindi il ticker viene ignorato
def vwap(tic):
    stock = yf.Ticker(tic)
    data = stock.history(period="30m", interval="1m")
    if data.empty:
        return None
    tot_pv = (data["Close"] * data["Volume"]).sum()
    tot_vol = data["Volume"].sum()
    return tot_pv / tot_vol if tot_vol else None

def rvol(tic, vol):
    stock = yf.Ticker(tic)
    data = stock.history(start="2024-04-01", end="2025-05-22")
    if data.empty:
        return 0
    avg = data["Volume"][-20:].mean()
    return vol / avg if avg else 0

def alert(txt: str):
    requests.post(API_TG, data={'chat_id': TG_CHAT, 'text': txt}, timeout=10)

def main_loop():
    while True:
        for tic in TICKERS:
            try:
                price, vol = quote(tic)
                fee, avail = borrow_data(tic)
                if fee < 100 or avail > 2000:
                    continue

                rv = rvol(tic, vol)
                pd = pdh(tic)
                vw = vwap(tic)
                trigger = None
                if rv >= 3 and price > pd:
                    trigger = 'RVOL + PDH breakout'
                elif vw and price > vw and price < pd and not isclose(price, pd, rel_tol=1e-3):
                    trigger = 'VWAP reclaim'

                if trigger:
                    msg = (f"BUY-WATCH {tic}\n"
                           f"Price {price:.2f} USD  RVOL {rv:.2f}\n"
                           f"Borrow fee {fee:.0f}% | Avail {avail} sh\n"
                           f"Trigger: {trigger}")
                    alert(msg)
                    logging.info('Alert sent %s', tic)
            except Exception as e:
                logging.error('%s: %s', tic, e)
        time.sleep(900)  # 15 min

if __name__ == '__main__':
    alert('TEST ALERT – worker avviato correttamente (yfinance)')
    main_loop()
