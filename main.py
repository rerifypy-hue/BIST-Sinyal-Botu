import os
import sys
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import requests
import psycopg2
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

# Yapılandırma
DB_URL = os.environ.get("DATABASE_URL")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# BIST 100 Hisseleri (Gerçek liste)
TICKERS = [
    "AEFES.IS", "AGHOL.IS", "AKBNK.IS", "AKCNS.IS", "AKFGY.IS", "AKSA.IS", "AKSEN.IS", "ALARK.IS", "ALBRK.IS", "ALFAS.IS",
    "ARCLK.IS", "ASELS.IS", "ASTOR.IS", "ASUZU.IS", "AYDEM.IS", "BAGFS.IS", "BERA.IS", "BIENP.IS", "BIMAS.IS", "BRMEN.IS",
    "BRYAT.IS", "BSOKE.IS", "CANTE.IS", "CCOLA.IS", "CIMSA.IS", "CWENE.IS", "DOAS.IS", "DOHOL.IS", "EGEEN.IS", "EKGYO.IS",
    "ENJSA.IS", "ENKAI.IS", "EREGL.IS", "EUPWR.IS", "FROTO.IS", "GARAN.IS", "GENIL.IS", "GESAN.IS", "GOKNR.IS", "GUBRF.IS",
    "GWIND.IS", "HALKB.IS", "HEKTS.IS", "IMASM.IS", "IPEKE.IS", "ISCTR.IS", "ISDMR.IS", "ISGYO.IS", "ISMEN.IS", "IZMDC.IS",
    "KAYSE.IS", "KCAER.IS", "KCHOL.IS", "KLSER.IS", "KONTR.IS", "KONYA.IS", "KORDS.IS", "KOZAA.IS", "KOZAL.IS", "KRDMD.IS",
    "MAVI.IS", "MGROS.IS", "MIATK.IS", "ODAS.IS", "OTKAR.IS", "OYAKC.IS", "PENTA.IS", "PETKM.IS", "PGSUS.IS", "QUAGR.IS",
    "REEDR.IS", "SAHOL.IS", "SASA.IS", "SAYAS.IS", "SDTTR.IS", "SISE.IS", "SKBNK.IS", "SMRTG.IS", "SOKM.IS", "TABGD.IS",
    "TAVHL.IS", "TCELL.IS", "THYAO.IS", "TKFEN.IS", "TMSN.IS", "TOASO.IS", "TSKB.IS", "TTKOM.IS", "TUPRS.IS", "TURSG.IS",
    "ULKER.IS", "VAKBN.IS", "VESBE.IS", "VESTL.IS", "YEOTK.IS", "YKBNK.IS", "YYLGD.IS", "ZOREN.IS"
]

def get_data(ticker):
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if df is None or df.empty:
            return None
        return df
    except Exception as e:
        print(f"{ticker} verisi alınamadı: {e}")
        return None

def calculate_indicators(df):
    if df is None:
        return None
    try:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        close = df['Close']
        volume = df['Volume']
        
        df['EMA20'] = ta.trend.EMAIndicator(close, window=20).ema_indicator()
        df['EMA50'] = ta.trend.EMAIndicator(close, window=50).ema_indicator()
        df['RSI'] = ta.momentum.RSIIndicator(close, window=14).rsi()
        df['ATR'] = ta.volatility.AverageTrueRange(df['High'], df['Low'], close, window=14).average_true_range()
        df['VolSMA20'] = volume.rolling(window=20).mean()
        
        return df
    except Exception as e:
        print(f"İndikatör hesaplama hatası: {e}")
        return None

def check_market_regime():
    df = get_data("XU100.IS")
    if df is None:
        print("BIST100 endeks verisi alınamadı.")
        return False
        
    df = calculate_indicators(df)
    if df is None:
        return False
        
    last_row = df.iloc[-1]
    
    is_safe = (last_row['EMA20'] > last_row['EMA50']) and (last_row['RSI'] > 45)
    return is_safe

def generate_signals(tickers):
    signals = []
    
    for ticker in tickers:
        print(f"Analiz ediliyor: {ticker}...")
        df = get_data(ticker)
        if df is None:
            continue
            
        df = calculate_indicators(df)
        if df is None:
            continue
            
        last_row = df.iloc[-1]
        
        condition_trend = last_row['EMA20'] > last_row['EMA50']
        condition_rsi = last_row['RSI'] > 55
        condition_vol = last_row['Volume'] > last_row['VolSMA20']
        
        if condition_trend and condition_rsi and condition_vol:
            entry = float(last_row['Close'])
            atr = float(last_row['ATR'])
            stop = entry - (1.5 * atr)
            tp = entry + (3 * atr)
            
            score = 0
            if condition_trend: score += 30
            if last_row['RSI'] > 60: score += 25
            if condition_vol: score += 20
            
            rr = (tp - entry) / (entry - stop)
            if rr >= 2: score += 25
            
            if score >= 70:
                signal = {
                    'symbol': ticker.replace('.IS', ''),
                    'signal': 'AL',
                    'entry': round(entry, 2),
                    'stop': round(stop, 2),
                    'tp': round(tp, 2),
                    'score': score,
                    'rr': round(rr, 2),
                    'result': 'ACIK'
                }
                signals.append(signal)
                
    signals.sort(key=lambda x: x['score'], reverse=True)
    return signals[:3]

def save_to_db(signals):
    if not DB_URL:
        print("DATABASE_URL ayarlı değil, veritabanına kayıt atlandı.")
        return

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        for s in signals:
            cur.execute("""
                INSERT INTO signals (date, symbol, signal, entry, stop, tp, score, result, rr)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (datetime.now(), s['symbol'], s['signal'], s['entry'], s['stop'], s['tp'], s['score'], s['result'], s['rr']))
            
        conn.commit()
        cur.close()
        conn.close()
        print(f"{len(signals)} sinyal veritabanına kaydedildi.")
    except Exception as e:
        print(f"Veritabanı hatası: {e}")

def create_pdf(signals):
    filename = "gunluk_rapor.pdf"
    doc = SimpleDocTemplate(filename, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    elements.append(Paragraph(f"BIST Günlük Sinyaller - {datetime.now().strftime('%Y-%m-%d')}", styles['Title']))
    
    data = [['Hisse', 'Sinyal', 'Giris', 'Stop', 'TP', 'Skor', 'R/R']]
    for s in signals:
        data.append([
            s['symbol'], s['signal'], s['entry'], s['stop'], s['tp'], s['score'], s['rr']
        ])
        
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey)
    ]))
    
    elements.append(table)
    elements.append(Paragraph("<br/><br/><i>Yatırım tavsiyesi değildir.</i>", styles['Normal']))
    
    doc.build(elements)
    return filename

def send_telegram(signals, pdf_path):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram kimlik bilgileri ayarlı değil.")
        return

    msg = f"📈 *BIST SEANS KAPANIŞI – GÜNLÜK SİNYALLER*\n\n"
    if not signals:
        msg += "📊 Seans Kapanışı: Bugün kriterlere uygun sinyal bulunamadı."
    else:
        for s in signals:
            msg += f"🔹 *{s['symbol']}*\n"
            msg += f"Sinyal: 🟢 *{s['signal']}*\n"
            msg += f"Giriş: {s['entry']}\n"
            msg += f"Stop: {s['stop']}\n"
            msg += f"TP: {s['tp']}\n"
            msg += f"Skor: {s['score']}/100\n"
            msg += f"R/R: {s['rr']}\n\n"
    
    msg += "⚠️ _Yatırım tavsiyesi değildir._"
    
    url_msg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url_msg, data={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'})
    
    if signals and pdf_path and os.path.exists(pdf_path):
        url_doc = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with open(pdf_path, 'rb') as f:
            requests.post(url_doc, data={'chat_id': CHAT_ID}, files={'document': f})

def main():
    print("BIST Bot Analizi Başlıyor...")
    
    is_safe = check_market_regime()
    if not is_safe:
        print("Piyasa koşulları olumsuz. Analiz durduruldu.")
        if TELEGRAM_TOKEN and CHAT_ID:
             url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
             requests.post(url, data={'chat_id': CHAT_ID, 'text': "📉 Piyasa koşulları olumsuz. Bugün işlem yapılmadı."})
        return

    signals = generate_signals(TICKERS)
    print(f"{len(signals)} sinyal üretildi.")
    
    if signals:
        save_to_db(signals)
        pdf_path = create_pdf(signals)
        send_telegram(signals, pdf_path)
    else:
        send_telegram([], None)
    
    print("Analiz tamamlandı.")

if __name__ == "__main__":
    main()
