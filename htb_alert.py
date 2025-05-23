
#!/usr/bin/env python3
"""
Hard-to-Borrow squeeze monitor
Checks 12 tickers every 15 minutes and sends Telegram alert when:
  1) Borrow fee > 100 %
  2) Borrow availability ≤ 2 000
  3) Either (a) RVOL ≥ 3 and price > previous-day high
     OR (b) price reclaims intraday VWAP after trading below.

Required environment variables:
  POLYGON_KEY – your Polygon.io API key
  FINTEL_KEY  – your Fintel API token
  TG_TOKEN    – Telegram bot token
  TG_CHAT     – chat_id where to send messages
"""
import os, time, requests, datetime, logging
from math import isclose

TICKERS = ['RGC','LUCY','PONY','BDMD','MRNO','TIVC','OMH','BRLS','CELU','ARQQ','NIVF','UP']

POLY   = os.getenv('POLYGON_KEY')
FINTEL = os.getenv('FINTEL_KEY')
TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT  = os.getenv('TG_CHAT')
if not all([POLY, FINTEL, TG_TOKEN, TG_CHAT]):
    raise SystemExit("Missing one or more environment variables.")

API_TG = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)

PDH_CACHE = {}
HEADERS = {'User-Agent':'HTB-Screener/1.0 (Render)'}

def pdh(tic):
    # Cache prev-day high for 1h
    if tic in PDH_CACHE and (datetime.datetime.utcnow() - PDH_CACHE[tic]['ts']).seconds < 3600:
        return PDH_CACHE[tic]['h']
    url = f'https://api.polygon.io/v2/aggs/ticker/{tic}/prev?adjusted=true&apiKey={POLY}'
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    h = r.json()['results'][0]['h']
    PDH_CACHE[tic] = {'h':h, 'ts':datetime.datetime.utcnow()}
    return h

def quote(tic):
    url = f'https://api.polygon.io/v1/last/stocks/{tic}?apiKey={POLY}'
    j = requests.get(url, headers=HEADERS, timeout=10).json()['last']
    return float(j['price']), int(j['size'])

def borrow_data(tic):
    url = f'https://fintel.io/api/ss/us/{tic}?token={FINTEL}'
    j = requests.get(url, headers=HEADERS, timeout=10).json()['data'][0]
    return float(j['fee'])*100, int(j['available'])

def vwap(tic):
    end = int(time.time()*1000)
    start = end - 30*60*1000
    url = f'https://api.polygon.io/v2/aggs/ticker/{tic}/range/1/minute/{start}/{end}?adjusted=true&sort=desc&apiKey={POLY}'
    bars = requests.get(url, timeout=10).json().get('results', [])
    if not bars:
        return None
    total_pv = sum(b['v']*b['c'] for b in bars)
    total_vol= sum(b['v'] for b in bars)
    return total_pv/total_vol if total_vol else None

def rvol(tic, today_vol):
    url = f'https://api.polygon.io/v2/aggs/ticker/{tic}/range/1/day/2024-04-01/2025-05-22?adjusted=true&apiKey={POLY}'
    data = requests.get(url, timeout=10).json().get('results', [])[-20:]
    if not data:
        return 0
    avg = sum(d['v'] for d in data)/len(data)
    return today_vol/avg if avg else 0

def alert(msg):
    requests.post(API_TG, data={'chat_id':TG_CHAT,'text':msg}, timeout=10)

def main_loop():
    while True:
        for tic in TICKERS:
            try:
                price, size = quote(tic)
                fee, avail  = borrow_data(tic)
                if fee < 100 or avail > 2000:
                    continue
                today_vol = size
                _rvol = rvol(tic, today_vol)
                _pdh  = pdh(tic)
                vw    = vwap(tic)
                trigger = None
                if _rvol >= 3 and price > _pdh:
                    trigger = 'RVOL + PDH breakout'
                elif vw and price > vw and price < _pdh and not isclose(price, _pdh, rel_tol=1e-3):
                    trigger = 'VWAP reclaim'
                if trigger:
                    msg = (f'BUY-WATCH {tic}\nPrice {price:.2f} USD  RVOL {_rvol:.2f}\n'"
                           f"Borrow fee {fee:.0f}% | Avail {avail} sh\nTrigger: {trigger}")
                    alert(msg)
                    logging.info('Alert sent %s', tic)
            except Exception as e:
                logging.error('%s: %s', tic, e)
        time.sleep(900)  # 15 minutes

if __name__ == '__main__':
    alert('TEST ALERT – worker avviato correttamente')
    main_loop()
