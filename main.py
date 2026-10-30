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
EMA_FAST = 9
EMA_SLOW = 21
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

RSI_MODE = "reversion"     # "reversion" | "trend"

# --- ЗВУК ---
SOUND_ENABLED = True
SOUND_FOR_NEUTRAL = False  # играть ли короткий сигнал при score == 0


# ---------- 1. ЗАГРУЗКА ДАННЫХ ----------
def fetch_ohlc():
    """Возвращает (highs, lows, closes) — синхронно отфильтрованные бары."""
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
        return [], [], []

    q = results[0]["indicators"]["quote"][0]
    highs, lows, closes = q.get("high"), q.get("low"), q.get("close")
    if not (highs and lows and closes):
        return [], [], []

    H, L, C = [], [], []
    for h, l, c in zip(highs, lows, closes):
        if h is None or l is None or c is None:
            continue
        H.append(h)
        L.append(l)
        C.append(c)
    return H, L, C


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
        return None, None, None
    ema_fast = ema_series(values, fast)
    ema_slow = ema_series(values, slow)
    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return None, None, None
    m, s = macd_line[-1], signal_line[-1]
    return m, s, m - s


def atr(highs, lows, closes, period=14):
    """Average True Range по Уайлдеру — значение для последнего бара."""
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


# ---------- 3. ЗВУК ----------
def _try_beep(freq_hz, duration_ms):
    """Windows-бип. True если удалось."""
    try:
        import winsound
        winsound.Beep(int(freq_hz), int(duration_ms))
        return True
    except Exception:
        return False


def _try_android_vibrate(duration_ms):
    """Вибрация на Android (QPython / SL4A)."""
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
    """Сила и направление сигнала → звук.
       |score| = 1..3, знак = быки/медведи. score=0 → тишина (или SOUND_FOR_NEUTRAL)."""
    if not SOUND_ENABLED:
        return
    if score == 0:
        if not SOUND_FOR_NEUTRAL:
            return
        _try_beep(500, 40) or _try_android_vibrate(40) or _try_bell(1)
        return

    strength = min(abs(score), 3)                          # 1..3
    duration = 80 + 40 * strength                          # 120..200 мс
    freqs = [400, 600, 800] if score > 0 else [800, 600, 400]

    # Windows: серия бипов с направлением
    ok = True
    for i in range(strength):
        if not _try_beep(freqs[i], duration):
            ok = False
            break
    if ok:
        return

    # Android: вибрация ∝ силе
    if _try_android_vibrate(100 * strength):
        return

    # Fallback: N звонков в терминал
    _try_bell(strength)


# ---------- 4. АНАЛИЗ ----------
def analyze():
    cfg = ASSETS[ASSET]
    highs, lows, closes = fetch_ohlc()

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
    atr_val = atr(highs, lows, closes, ATR_PERIOD)

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

    if atr_val is not None:
        atr_pct = atr_val / price * 100.0
        print(f"📏 ATR({ATR_PERIOD}): {atr_val:.{dec}f} "
              f"({atr_pct:.3f}% от цены)")

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
    print(f"🧭 Сводка (score={score:+d}): {verdict}")

    # Звуковое сопровождение: сила и направление ∝ score
    play_signal(score)


# ---------- 5. ЦИКЛ ----------
def main():
    cfg = ASSETS[ASSET]
    print(f"🚀 Анализатор {cfg['name']} ({cfg['ticker']}) запущен.")
    print(f"   Обновление каждые {INTERVAL} сек. Остановить: Ctrl+C.")
    print(f"   Звук: {'вкл' if SOUND_ENABLED else 'выкл'}, "
          f"сила ∝ |score|, направление ∝ знаку score.")
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