import json
import os
import sys
from pathlib import Path

import requests

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.getenv("CHANNEL_ID", "@kp_iranian")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()

STATE_FILE = Path("state.json")
API = f"https://api.telegram.org/bot{TOKEN}"


def load_state():
    if not STATE_FILE.exists():
        return {"last_update_id": 0, "queue": [], "published": 0}

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    return {
        "last_update_id": int(data.get("last_update_id", 0)),
        "queue": data.get("queue", []),
        "published": int(data.get("published", 0)),
    }


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def telegram(method, payload=None):
    response = requests.post(
        f"{API}/{method}",
        json=payload or {},
        timeout=60,
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result)

    return result["result"]


def collect_new_photos(state):
    updates = telegram(
        "getUpdates",
        {
            "offset": state["last_update_id"] + 1,
            "timeout": 0,
            "allowed_updates": ["message"],
        },
    )

    added = 0

    for update in updates:
        state["last_update_id"] = max(
            state["last_update_id"],
            update["update_id"],
        )

        message = update.get("message", {})
        sender_id = str(message.get("from", {}).get("id", ""))

        if ADMIN_USER_ID and sender_id != ADMIN_USER_ID:
            continue

        photos = message.get("photo", [])
        if not photos:
            continue

        largest_photo = photos[-1]
        file_id = largest_photo["file_id"]
        caption = message.get("caption", "").strip()

        state["queue"].append(
            {
                "file_id": file_id,
                "caption": caption,
                "sender_id": sender_id,
            }
        )
        added += 1

    return added


def publish_one(state):
    if not state["queue"]:
        print("صف عکس‌ها خالی است.")
        return False

    item = state["queue"][0]

    default_caption = (
        "فروشگاه ایرانیان\n"
        "جهت سفارش و استعلام قیمت با ما در ارتباط باشید.\n\n"
        "تلگرام: @kp_iranian"
    )

    telegram(
        "sendPhoto",
        {
            "chat_id": CHANNEL_ID,
            "photo": item["file_id"],
            "caption": item["caption"] or default_caption,
        },
    )

    state["queue"].pop(0)
    state["published"] += 1
    print("یک عکس با موفقیت منتشر شد.")
    return True


def main():
    state = load_state()

    added = collect_new_photos(state)
    print(f"{added} عکس جدید وارد صف شد.")

    publish_one(state)
    save_state(state)

    print(f"تعداد باقی‌مانده در صف: {len(state['queue'])}")
    print(f"تعداد کل منتشرشده: {state['published']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"خطا: {exc}", file=sys.stderr)
        raise
