
# -*- coding: utf-8 -*-
import json
import ssl
import certifi
import time
import urllib.request
from datetime import datetime

# --- НАСТРОЙКИ ---
SYMBOL = "GC=F"        # Золото (фьючерс). Для спота можно попробовать "XAUUSD=X"
INTERVAL = 60          # Запрос каждую минуту
RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9


# ---------- 1. ЗАГРУЗКА ДАННЫХ ----------

def fetch_closes():
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{SYMBOL}?interval=1m&range=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    # Создаём контекст с сертификатами из certifi
    context = ssl.create_default_context(cafile=certifi.where())
    
    with urllib.request.urlopen(req, timeout=15, context=context) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)

    result = data["chart"]["result"][0]
    quotes = result["indicators"]["quote"][0]["close"]
    closes = [c for c in quotes if c is not None]
    return closes


# ---------- 2. ИНДИКАТОРЫ (вручную) ----------
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
    """RSI по Уайлдеру (сглаживание как в MT4/TradingView)."""
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

    # Выравниваем по длине: ema_fast длиннее на (slow - fast) значений
    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]

    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return None, None, None

    m = macd_line[-1]
    s = signal_line[-1]
    return m, s, m - s


# ---------- 3. АНАЛИЗ И ВЫВОД ----------
def analyze():
    closes = fetch_closes()
    if len(closes) < MACD_SLOW + MACD_SIGNAL:
        print("⏳ Недостаточно данных (рынок закрыт или мало истории).")
        return

    price = closes[-1]
    r = rsi(closes, RSI_PERIOD)
    m, s, h = macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    e_fast = ema_series(closes, EMA_FAST)
    e_slow = ema_series(closes, EMA_SLOW)

    print("\n" + "=" * 42)
    print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"💰 Цена: {price:.2f} USD | Баров: {len(closes)}")

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
        print(f"📊 MACD: {m:.3f} | сигнал: {s:.3f} | гист: {h:+.3f} → {direction}")

    if e_fast and e_slow:
        direction = "восходящий" if e_fast[-1] > e_slow[-1] else "нисходящий"
        print(f"📉 EMA{EMA_FAST}={e_fast[-1]:.2f} / EMA{EMA_SLOW}={e_slow[-1]:.2f} → {direction}")

    # Итоговая сводка по трём индикаторам
    score = 0
    if r is not None:
        score += 1 if r < 30 else (-1 if r > 70 else 0)
    if m is not None:
        score += 1 if m > s else -1
    if e_fast and e_slow:
        score += 1 if e_fast[-1] > e_slow[-1] else -1

    verdict = {
        3: "🟢 Сильный бычий сигнал",
        2: "🟢 Умеренно бычий",
        1: "🟡 Слабый бычий",
        0: "⚪ Нейтрально",
        -1: "🟡 Слабый медвежий",
        -2: "🔴 Умеренно медвежий",
        -3: "🔴 Сильный медвежий",
    }[score]
    print(f"🧭 Сводка: {verdict}")


# ---------- 4. ЦИКЛ ----------
def main():
    print(f"🚀 Анализатор золота запущен ({SYMBOL}). Обновление каждые {INTERVAL} сек.")
    print("Остановить: Ctrl+C в консоли QPython.")
    while True:
        try:
            analyze()
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Остановлено.")