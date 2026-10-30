# -*- coding: utf-8 -*-
import json
import ssl
import certifi
import time
import math
import traceback
import urllib.request
import urllib.error
from datetime import datetime

# --- НАСТРОЙКИ ---
ASSET = "btc"   # "gold" | "btc"

ASSETS = {
    "gold": {
        "ticker":   "GC=F",
        "name":     "Золото (фьючерс)",
        "range":    "5d",
        "decimals": 2,
    },
    "btc": {
        "ticker":   "BTC-USD",
        "name":     "Bitcoin",
        "range":    "1d",
        "decimals": 2,
    },
}

INTERVAL = 60
RSI_PERIOD = 14
ATR_PERIOD = 14
ADX_PERIOD = 14
BB_PERIOD = 20
BB_MULT = 2.0
VOL_AVG_PERIOD = 20
EMA_FAST = 9
EMA_SLOW = 21
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

RSI_MODE = "reversion"     # "reversion" | "trend"

# --- ЗВУК ---
SOUND_ENABLED = True
SOUND_FOR_NEUTRAL = False


# ---------- 1. ЗАГРУЗКА ДАННЫХ ----------
def fetch_ohlcv():
    """Возвращает (highs, lows, closes, volumes) — отфильтрованные бары."""
    cfg = ASSETS[ASSET]
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{cfg['ticker']}?interval=1m&range={cfg['range']}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    context = ssl.create_default_context(cafile=certifi.where())

    with urllib.request.urlopen(req, timeout=15, context=context) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)

    results = data.get("chart", {}).get("result") or []
    if not results:
        return [], [], [], []

    q = results[0]["indicators"]["quote"][0]
    highs, lows = q.get("high"), q.get("low")
    closes, volumes = q.get("close"), q.get("volume")
    
    if not (highs and lows and closes and volumes):
        return [], [], [], []

    H, L, C, V = [], [], [], []
    for h, l, c, v in zip(highs, lows, closes, volumes):
        # Для объема иногда бывает None, заменяем на 0
        v_clean = v if v is not None else 0
        if h is None or l is None or c is None:
            continue
        H.append(h)
        L.append(l)
        C.append(c)
        V.append(v_clean)
    return H, L, C, V


# ---------- 2. ИНДИКАТОРЫ ----------
def ema_series(values, period):
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0 and avg_gain == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        return None, None, None, None
    ema_fast = ema_series(values, fast)
    ema_slow = ema_series(values, slow)
    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return None, None, None, None
    
    m, s = macd_line[-1], signal_line[-1]
    # Гистограмма текущая и предыдущая (чтобы понять, растет импульс или падает)
    hist_current = m - s
    hist_prev = macd_line[-2] - signal_line[-2] if len(signal_line) > 1 else hist_current
    return m, s, hist_current, hist_prev


def atr(highs, lows, closes, period=14):
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs = []
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    a = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        a = (a * (period - 1) + trs[i]) / period
    return a


def adx(highs, lows, closes, period=14):
    """Возвращает (ADX, +DI, -DI)"""
    n = min(len(highs), len(lows), len(closes))
    if n < period * 2:
        return None, None, None
    trs, plus_dms, minus_dms = [], [], []
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)
    
    smoothed_tr = [sum(trs[:period])]
    smoothed_plus = [sum(plus_dms[:period])]
    smoothed_minus = [sum(minus_dms[:period])]
    
    for i in range(period, len(trs)):
        smoothed_tr.append(smoothed_tr[-1] - (smoothed_tr[-1]/period) + trs[i])
        smoothed_plus.append(smoothed_plus[-1] - (smoothed_plus[-1]/period) + plus_dms[i])
        smoothed_minus.append(smoothed_minus[-1] - (smoothed_minus[-1]/period) + minus_dms[i])
        
    plus_di = [100 * p / t if t != 0 else 0 for p, t in zip(smoothed_plus, smoothed_tr)]
    minus_di = [100 * m / t if t != 0 else 0 for m, t in zip(smoothed_minus, smoothed_tr)]
    
    dx = [100 * abs(p - m) / (p + m) if (p + m) != 0 else 0 for p, m in zip(plus_di, minus_di)]
    
    if len(dx) < period: return None, None, None
    adx_val = sum(dx[:period]) / period
    for i in range(period, len(dx)):
        adx_val = (adx_val * (period - 1) + dx[i]) / period
        
    return adx_val, plus_di[-1], minus_di[-1]


def bollinger(values, period=20, mult=2.0):
    """Возвращает (Верхняя, Средняя, Нижняя)"""
    if len(values) < period: return None, None, None
    sma = sum(values[-period:]) / period
    variance = sum((x - sma) ** 2 for x in values[-period:]) / period
    std_dev = math.sqrt(variance)
    return sma + (std_dev * mult), sma, sma - (std_dev * mult)


# ---------- 3. ЗВУК ----------
def _try_beep(freq_hz, duration_ms):
    try:
        import winsound
        winsound.Beep(int(freq_hz), int(duration_ms))
        return True
    except Exception:
        return False

def _try_android_vibrate(duration_ms):
    try:
        import android
        android.Android().vibrate(int(duration_ms))
        return True
    except Exception:
        pass
    try:
        import androidhelper as android
        android.Android().vibrate(int(duration_ms))
        return True
    except Exception:
        return False

def _try_bell(count):
    for _ in range(max(1, count)):
        print("\a", end="", flush=True)
        time.sleep(0.1)

def play_signal(score):
    if not SOUND_ENABLED: return
    if score == 0:
        if not SOUND_FOR_NEUTRAL: return
        _try_beep(500, 40) or _try_android_vibrate(40) or _try_bell(1)
        return
    strength = min(abs(score), 3)
    duration = 80 + 40 * strength
    freqs = [400, 600, 800] if score > 0 else [800, 600, 400]
    ok = True
    for i in range(strength):
        if not _try_beep(freqs[i], duration):
            ok = False
            break
    if ok: return
    if _try_android_vibrate(100 * strength): return
    _try_bell(strength)


# ---------- 4. АНАЛИЗ ----------
def analyze():
    cfg = ASSETS[ASSET]
    highs, lows, closes, volumes = fetch_ohlcv()

    if not closes or len(closes) < MACD_SLOW + MACD_SIGNAL:
        print(f"\n⏳ {datetime.now().strftime('%H:%M:%S')} — нет данных "
              f"({cfg['name']}: рынок закрыт или мало истории).")
        return

    price = closes[-1]
    dec = cfg["decimals"]
    
    r = rsi(closes, RSI_PERIOD)
    m, s, h, h_prev = macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    e_fast = ema_series(closes, EMA_FAST)
    e_slow = ema_series(closes, EMA_SLOW)
    atr_val = atr(highs, lows, closes, ATR_PERIOD)
    adx_val, plus_di, minus_di = adx(highs, lows, closes, ADX_PERIOD)
    bb_up, bb_mid, bb_low = bollinger(closes, BB_PERIOD, BB_MULT)
    
    # Средний объем
    avg_vol = sum(volumes[-VOL_AVG_PERIOD:]) / VOL_AVG_PERIOD if len(volumes) >= VOL_AVG_PERIOD else 0

    print("\n" + "=" * 50)
    print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"💱 {cfg['name']} ({cfg['ticker']})")
    print(f"💰 Цена: {price:.{dec}f} USD | Баров: {len(closes)}")

    # --- RSI ---
    if r is not None:
        if r < 30: tag = "перепродан (ожидаем отскок вверх)"
        elif r > 70: tag = "перекуплен (риск коррекции)"
        elif r > 50: tag = "бычий настрой (выше 50)"
        else: tag = "медвежий настрой (ниже 50)"
        print(f"📈 RSI({RSI_PERIOD}): {r:.2f} → {tag}")

    # --- MACD ---
    if m is not None:
        if m > s:
            direction = "БЫЧИЙ"
            if h > h_prev: tag = "импульс растет"
            else: tag = "импульс слабеет"
        else:
            direction = "МЕДВЕЖИЙ"
            if h < h_prev: tag = "давление растет"
            else: tag = "давление слабеет"
        print(f"📊 MACD: {m:.4f} | сигнал: {s:.4f} | гист: {h:+.4f}")
        print(f"   → {direction} ({tag})")

    # --- EMA ---
    if e_fast and e_slow:
        diff = e_fast[-1] - e_slow[-1]
        if diff > 0:
            tag = "восходящий тренд" if price > e_fast[-1] else "коррекция к EMA9"
        else:
            tag = "нисходящий тренд" if price < e_fast[-1] else "отскок к EMA9"
        print(f"📉 EMA{EMA_FAST}={e_fast[-1]:.{dec}f} / EMA{EMA_SLOW}={e_slow[-1]:.{dec}f}")
        print(f"   → {tag}")

    # --- ATR (Волатильность) ---
    if atr_val is not None:
        atr_pct = atr_val / price * 100.0
        if atr_pct < 0.05: tag = "очень низкая (флэт, сжатие)"
        elif atr_pct < 0.15: tag = "низкая (спокойный рынок)"
        elif atr_pct < 0.3: tag = "умеренная (нормальный ход)"
        else: tag = "высокая (волатильный рынок)"
        print(f"📏 ATR({ATR_PERIOD}): {atr_val:.{dec}f} ({atr_pct:.3f}%) → {tag}")

    # --- ADX (Сила тренда) ---
    if adx_val is not None:
        if adx_val < 20: tag = "ФЛЭТ / нет тренда"
        elif adx_val < 25: tag = "зарождение тренда"
        else: tag = "СИЛЬНЫЙ ТРЕНД"
        di_dir = "Быки сильнее (+DI)" if plus_di > minus_di else "Медведи сильнее (-DI)"
        print(f"🧗 ADX({ADX_PERIOD}): {adx_val:.1f} → {tag}")
        print(f"   +DI: {plus_di:.1f} | -DI: {minus_di:.1f} → {di_dir}")

    # --- Bollinger Bands ---
    if bb_up is not None:
        band_width_pct = (bb_up - bb_low) / bb_mid * 100.0
        if price > bb_up: tag = "ПРОБОЙ ВЕРХНЕЙ (перегрев)"
        elif price < bb_low: tag = "ПРОБОЙ НИЖНЕЙ (перепродажа)"
        elif band_width_pct < 0.2: tag = "СЖАТИЕ (сквиз, ждем импульс)"
        else: tag = "внутри канала"
        print(f"🎈 BB({BB_PERIOD}): {bb_low:.{dec}f} | {bb_mid:.{dec}f} | {bb_up:.{dec}f}")
        print(f"   → {tag}")

    # --- Объем ---
    current_vol = volumes[-1]
    if avg_vol > 0:
        vol_ratio = current_vol / avg_vol
        if vol_ratio > 1.5: tag = "ВСПЛЕСК (подтверждение движения)"
        elif vol_ratio < 0.5: tag = "низкий (нет интереса)"
        else: tag = "средний (норма)"
        print(f"📦 Объем: {current_vol:.0f} (ср. {avg_vol:.0f}) → {tag}")

    # Итоговый счёт (логика не изменена)
    score = 0
    if r is not None:
        if RSI_MODE == "reversion":
            score += 1 if r < 30 else (-1 if r > 70 else 0)
        else:
            score += 1 if r > 50 else -1
    if m is not None:
        score += 1 if m > s else -1
    if e_fast and e_slow:
        score += 1 if e_fast[-1] > e_slow[-1] else -1

    verdict = {
        3:  "🟢 Сильный бычий сигнал",
        2:  "🟢 Умеренно бычий",
        1:  "🟡 Слабый бычий",
        0:  "⚪ Нейтрально",
        -1: "🟡 Слабый медвежий",
        -2: "🔴 Умеренно медвежий",
        -3: "🔴 Сильный медвежий",
    }[score]
    print("-" * 50)
    print(f"🧭 Сводка (score={score:+d}): {verdict}")
    
    play_signal(score)


# ---------- 5. ЦИКЛ ----------
def main():
    cfg = ASSETS[ASSET]
    print(f"🚀 Анализатор {cfg['name']} ({cfg['ticker']}) запущен.")
    print(f"   Обновление каждые {INTERVAL} сек. Остановить: Ctrl+C.")
    while True:
        try:
            analyze()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("⚠️ Yahoo rate limit (429). Жду 120 сек...")
                time.sleep(120)
                continue
            print(f"⚠️ HTTP {e.code}: {e.reason}")
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            traceback.print_exc()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Остановлено.")