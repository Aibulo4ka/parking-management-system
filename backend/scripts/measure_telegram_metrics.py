"""
Замер метрик Telegram-интеграции: latency и throughput.

Запуск изнутри контейнера:
    docker exec parking_backend python scripts/measure_telegram_metrics.py
"""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

# Контейнер запущен из /app, наш пакет — app
sys.path.insert(0, "/app")

from app.services.telegram_service import telegram_service, TelegramServiceError

CHAT_ID = "1160248718"  # привязанный chat_id тестового юзера tg-test@example.com
LATENCY_N = 20
LATENCY_GAP_S = 0.5
THROUGHPUT_N = 50  # сколько сообщений шлём тайт-лупом
OUTPUT_FILE = Path("/app/scripts/telegram_metrics_results.json")


async def measure_latency(n: int = LATENCY_N) -> dict:
    print(f"=== LATENCY: {n} последовательных sendMessage, пауза {LATENCY_GAP_S}s ===")
    samples_ms: list[float] = []
    failures = 0

    for i in range(1, n + 1):
        t0 = time.monotonic()
        try:
            await telegram_service.send_message(
                CHAT_ID, f"[метрика latency] замер #{i}/{n}"
            )
            dt_ms = (time.monotonic() - t0) * 1000.0
            samples_ms.append(dt_ms)
            print(f"  #{i:>2}: {dt_ms:7.1f} ms")
        except TelegramServiceError as exc:
            failures += 1
            print(f"  #{i:>2}: FAIL ({exc})")
        await asyncio.sleep(LATENCY_GAP_S)

    if not samples_ms:
        return {"samples": [], "failures": failures, "stats": None}

    sorted_samples = sorted(samples_ms)
    n_ok = len(samples_ms)
    p95_idx = max(0, min(n_ok - 1, int(round(0.95 * (n_ok - 1)))))

    stats = {
        "count_ok": n_ok,
        "count_fail": failures,
        "mean_ms": round(statistics.mean(samples_ms), 1),
        "median_ms": round(statistics.median(samples_ms), 1),
        "p95_ms": round(sorted_samples[p95_idx], 1),
        "min_ms": round(min(samples_ms), 1),
        "max_ms": round(max(samples_ms), 1),
        "stdev_ms": round(statistics.stdev(samples_ms), 1) if n_ok > 1 else 0.0,
    }
    print(f"\nlatency stats: {json.dumps(stats, ensure_ascii=False)}")
    return {"samples_ms": [round(x, 1) for x in samples_ms], "stats": stats}


async def measure_throughput(n: int = THROUGHPUT_N) -> dict:
    print(f"\n=== THROUGHPUT: {n} сообщений подряд без пауз ===")
    t_start = time.monotonic()
    sent = 0
    failed = 0

    for i in range(1, n + 1):
        try:
            await telegram_service.send_message(
                CHAT_ID, f"[метрика throughput] {i}/{n}"
            )
            sent += 1
        except TelegramServiceError as exc:
            failed += 1
            # При rate-limit Telegram возвращает 429; останавливаемся, если стабильно падает
            if failed >= 5 and failed > sent:
                print(f"  слишком много отказов подряд (failed={failed}), останавливаюсь")
                break

    elapsed_s = time.monotonic() - t_start
    rate = sent / elapsed_s if elapsed_s > 0 else 0.0
    delivery_rate = sent / (sent + failed) if (sent + failed) > 0 else 0.0

    stats = {
        "elapsed_s": round(elapsed_s, 2),
        "sent": sent,
        "failed": failed,
        "messages_per_second": round(rate, 2),
        "delivery_rate": round(delivery_rate, 3),
    }
    print(f"throughput stats: {json.dumps(stats, ensure_ascii=False)}")
    return stats


async def main():
    print("Telegram metrics — старт")
    print(f"chat_id={CHAT_ID}")
    print(f"bot configured: {telegram_service.is_configured}\n")

    if not telegram_service.is_configured:
        print("Бот не сконфигурирован, выходим")
        sys.exit(1)

    latency = await measure_latency()
    throughput = await measure_throughput()

    payload = {
        "chat_id": CHAT_ID,
        "latency": latency,
        "throughput": throughput,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nрезультаты сохранены в {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
