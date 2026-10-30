# -*- coding: utf-8 -*-
import json
import ssl
import certifi
import time
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
        "range":    "5d",     # 5 дней — чтобы данные остались после выходных
        "decimals": 2,
    },
    "btc": {
        "ticker":   "BTC-USD",
        "name":     "Bitcoin",
        "range":    "1d",     # крипта торгуется 24/7
        "decimals": 2,
    },
}

INTERVAL = 60
RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

# Логика RSI в итоговом счёте:
#   "reversion" — RSI<30 → +1, RSI>70 → -1  (контртренд, как было)
#   "trend"     — RSI>50 → +1, RSI<50 → -1  (по тренду)
RSI_MODE = "reversion"


# ---------- 1. ЗАГРУЗКА ДАННЫХ ----------
def fetch_closes():
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
        return []
    quotes = results[0]["indicators"]["quote"][0]["close"]
    return [c for c in quotes if c is not None]


# ---------- 2. ИНДИКАТОРЫ ----------
def ema_series(values, period):
    """EMA по классической формуле, seed = SMA первых period значений."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values, period=14):
    """RSI по Уайлдеру. Флэт (avg_gain=avg_loss=0) → 50."""
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
    """Возвращает (MACD-линия, сигнальная, гистограмма) для последнего бара."""
    if len(values) < slow + signal:
        return None, None, None
    ema_fast = ema_series(values, fast)
    ema_slow = ema_series(values, slow)

    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]

    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return None, None, None

    m = macd_line[-1]
    s = signal_line[-1]
    return m, s, m - s


# ---------- 3. АНАЛИЗ ----------
def analyze():
    cfg = ASSETS[ASSET]
    closes = fetch_closes()

    if not closes or len(closes) < MACD_SLOW + MACD_SIGNAL:
        print(f"\n⏳ {datetime.now().strftime('%H:%M:%S')} — нет данных "
              f"({cfg['name']}: рынок закрыт или мало истории).")
        return

    price = closes[-1]
    dec = cfg["decimals"]
    r = rsi(closes, RSI_PERIOD)
    m, s, h = macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    e_fast = ema_series(closes, EMA_FAST)
    e_slow = ema_series(closes, EMA_SLOW)

    print("\n" + "=" * 48)
    print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"💱 {cfg['name']} ({cfg['ticker']})")
    print(f"💰 Цена: {price:.{dec}f} USD | Баров: {len(closes)}")

    if r is not None:
        if r < 30:
            tag = "перепродан → возможен рост"
        elif r > 70:
            tag = "перекуплен → возможна коррекция"
        else:
            tag = "нейтрально"
        print(f"📈 RSI({RSI_PERIOD}): {r:.2f} ({tag})")

    if m is not None:
        direction = "бычий" if m > s else "медвежий"
        print(f"📊 MACD: {m:.4f} | сигнал: {s:.4f} | гист: {h:+.4f} → {direction}")

    if e_fast and e_slow:
        direction = "восходящий" if e_fast[-1] > e_slow[-1] else "нисходящий"
        print(f"📉 EMA{EMA_FAST}={e_fast[-1]:.{dec}f} / "
              f"EMA{EMA_SLOW}={e_slow[-1]:.{dec}f} → {direction}")

    # Итоговый счёт
    score = 0
    if r is not None:
        if RSI_MODE == "reversion":
            score += 1 if r < 30 else (-1 if r > 70 else 0)
        else:  # "trend"
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
    print(f"🧭 Сводка (score={score:+d}): {verdict}")


# ---------- 4. ЦИКЛ ----------
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