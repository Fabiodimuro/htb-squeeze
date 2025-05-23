#!/usr/bin/env python3
"""Hard-to-Borrow squeeze monitor – Render worker
Checks 12 tickers every 15 min and sends a Telegram alert when:
  1) borrow fee > 100 %
  2) borrow availability ≤ 2 000
  3) Either
       a) RVOL ≥ 3 and price > previous-day high,  OR
       b) price reclaims intraday VWAP after trading below.
ENV VARS: POLYGON_KEY, FINTEL_KEY, TG_TOKEN, TG_CHAT
"""
import os, time, requests, datetime, logging
from math import isclose

TICKERS = [
    # senza S-3 / ATM
    'RGC','LUCY','PONY','BDMD','MRNO',
    'TIVC','OMH','BRLS','NIVF','UP',      # 10 già ok
    'HNRA','DUO','CXAI','LOCL','LUNR',
    'ENSC','SAI','GCT','GDC','APLM',
    'SPRC','HCWB','PEGY','NOGN','AMDX',
    'TNYA','SERA','PXLW','AKAN','INPX'    # 20 sostituti
]
POLY   = os.getenv('POLYGON_KEY')
FINTEL = os.getenv('FINTEL_KEY')
TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT  = os.getenv('TG_CHAT')
API_TG   = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.INFO)

PDH_CACHE = {}
HEADERS = {'User-Agent':'HTB-Screener/1.0 (Render)'}

def pdh(tic):
    if tic in PDH_CACHE and (datetime.datetime.utcnow()-PDH_CACHE[tic]['ts']).seconds<3600:
        return PDH_CACHE[tic]['h']
    url=f'https://api.polygon.io/v2/aggs/ticker/{tic}/prev?adjusted=true&apiKey={POLY}'
    h=requests.get(url,timeout=10).json()['results'][0]['h']
    PDH_CACHE[tic]={'h':h,'ts':datetime.datetime.utcnow()}
    return h
def quote(tic):
    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{tic}?apiKey={POLY}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        js = r.json()
        if 'ticker' not in js:
            logging.warning(f"{tic}: 'ticker' not in response JSON: {js}")
            raise ValueError('no snapshot')
        snap = js['ticker']
        price = snap['lastTrade']['p'] if snap.get('lastTrade') else snap['day']['c']
        vol   = snap['day']['v']
        return float(price), int(vol)
    except Exception as e:
        logging.error(f"quote() error for {tic} – URL: {url} – Response: {r.text} – {e}")
        raise ValueError('no snapshot')
def borrow_data(tic):
    j=requests.get(f'https://fintel.io/api/ss/us/{tic}?token={FINTEL}',
                   headers=HEADERS,timeout=10).json()['data'][0]
    return float(j['fee'])*100, int(j['available'])

def vwap(tic):
    end=int(time.time()*1000); start=end-30*60*1000
    url=(f'https://api.polygon.io/v2/aggs/ticker/{tic}/range/1/minute/'
         f'{start}/{end}?adjusted=true&sort=desc&apiKey={POLY}')
    bars=requests.get(url,timeout=10).json().get('results',[])
    if not bars: return None
    tot_pv=sum(b['v']*b['c'] for b in bars)
    tot_vol=sum(b['v'] for b in bars)
    return tot_pv/tot_vol if tot_vol else None

def rvol(tic,vol):
    url=(f'https://api.polygon.io/v2/aggs/ticker/{tic}/range/1/day/'
         f'2024-04-01/2025-05-22?adjusted=true&apiKey={POLY}')
    data=requests.get(url,timeout=10).json().get('results',[])[-20:]
    if not data: return 0
    avg=sum(d['v'] for d in data)/len(data)
    return vol/avg if avg else 0

def alert(txt:str):
    requests.post(API_TG,data={'chat_id':TG_CHAT,'text':txt},timeout=10)

def main_loop():
    while True:
        for tic in TICKERS:
            try:
                price,vol = quote(tic)
                fee,avail = borrow_data(tic)
                if fee<100 or avail>2000:
                    continue

                rv = rvol(tic,vol)
                pd = pdh(tic)
                vw = vwap(tic)
                trigger=None
                if rv>=3 and price>pd:
                    trigger='RVOL + PDH breakout'
                elif vw and price>vw and price<pd and not isclose(price,pd,rel_tol=1e-3):
                    trigger='VWAP reclaim'

                if trigger:
                    msg=(f"BUY-WATCH {tic}\n"
                         f"Price {price:.2f} USD  RVOL {rv:.2f}\n"
                         f"Borrow fee {fee:.0f}% | Avail {avail} sh\n"
                         f"Trigger: {trigger}")
                    alert(msg)
                    logging.info('Alert sent %s',tic)
            except Exception as e:
                logging.error('%s: %s',tic,e)
        time.sleep(900)  # 15 min

if __name__ == '__main__':
    alert('TEST ALERT – worker avviato correttamente')
    main_loop()
