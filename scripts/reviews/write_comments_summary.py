#!/usr/bin/env python3
"""
Small companion to write_summary.py, split out because fetch-comments.yml
is its own standalone workflow (see that file for why) and doesn't want to
pull in the full review-pipeline summary format.

Usage:
    python write_comments_summary.py --report tmp/report_comments.json
"""
import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    print("## 💬 Review comments — отчёт о запуске\n")

    if not os.path.exists(args.report):
        print("⚠️ Отчёт не найден (шаг мог быть пропущен — latest.json ещё не существует)")
        return

    try:
        with open(args.report, encoding="utf-8") as f:
            r = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ Не удалось прочитать отчёт: {e}")
        return

    if r.get("ok"):
        print(f"✅ Проверено отзывов: **{r.get('reviews_checked', 0)}**  ")
        print(f"Отзывов с комментариями (всего): **{r.get('reviews_with_comments', 0)}**  ")
        print(f"Новых комментариев обнаружено за этот запуск: **{r.get('new_comments_detected', 0)}**")
    else:
        print(f"❌ Ошибка: `{r.get('error', 'unknown')}`")


if __name__ == "__main__":
    main()
