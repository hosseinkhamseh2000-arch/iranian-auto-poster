import asyncio
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

BASE_DIR = Path(__file__).resolve().parent
PHOTOS_DIR = BASE_DIR / "photos"
STATE_FILE = BASE_DIR / "state.json"
CAPTIONS_FILE = BASE_DIR / "captions.txt"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tehran").strip()
POST_TIMES = [
    item.strip()
    for item in os.getenv("POST_TIMES", "09:00,15:00,21:00").split(",")
    if item.strip()
]
RANDOM_ORDER = os.getenv("RANDOM_ORDER", "false").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def validate_config() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN در فایل .env وارد نشده است.")
    if not CHANNEL_ID:
        raise RuntimeError("CHANNEL_ID در فایل .env وارد نشده است.")
    for value in POST_TIMES:
        try:
            hour, minute = map(int, value.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError as exc:
            raise RuntimeError(
                f"زمان نامعتبر است: {value}. نمونه درست: 09:00"
            ) from exc


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"posted": []}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"posted": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_photos() -> list[Path]:
    return sorted(
        path
        for path in PHOTOS_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def choose_next_photo() -> Path | None:
    photos = get_photos()
    if not photos:
        return None

    state = load_state()
    posted = set(state.get("posted", []))
    remaining = [p for p in photos if str(p.relative_to(BASE_DIR)) not in posted]

    if not remaining:
        posted.clear()
        remaining = photos

    photo = random.choice(remaining) if RANDOM_ORDER else remaining[0]
    relative = str(photo.relative_to(BASE_DIR))
    posted.add(relative)
    save_state({"posted": sorted(posted)})
    return photo


def get_caption(photo: Path) -> str:
    captions = {}
    default_caption = ""

    if CAPTIONS_FILE.exists():
        for raw_line in CAPTIONS_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                filename, caption = line.split("|", 1)
                captions[filename.strip()] = caption.strip()
            elif not default_caption:
                default_caption = line

    caption = captions.get(photo.name, default_caption)
    today = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y/%m/%d")
    return caption.replace("{date}", today).replace("{filename}", photo.stem)


async def publish_photo() -> None:
    photo = choose_next_photo()
    if photo is None:
        logger.warning("هیچ عکسی داخل پوشه photos پیدا نشد.")
        return

    caption = get_caption(photo)
    bot = Bot(token=BOT_TOKEN)

    try:
        with photo.open("rb") as image:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=image,
                caption=caption or None,
            )
        logger.info("عکس ارسال شد: %s", photo.name)
    except TelegramError:
        logger.exception("ارسال عکس ناموفق بود.")
        # عکس ناموفق را دوباره قابل ارسال می‌کنیم.
        state = load_state()
        relative = str(photo.relative_to(BASE_DIR))
        state["posted"] = [
            item for item in state.get("posted", []) if item != relative
        ]
        save_state(state)


async def test_connection() -> None:
    bot = Bot(token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info("ربات متصل شد: @%s", me.username)


async def main() -> None:
    validate_config()
    PHOTOS_DIR.mkdir(exist_ok=True)
    await test_connection()

    scheduler = AsyncIOScheduler(timezone=ZoneInfo(TIMEZONE))

    for value in POST_TIMES:
        hour, minute = map(int, value.split(":"))
        scheduler.add_job(
            publish_photo,
            CronTrigger(
                hour=hour,
                minute=minute,
                timezone=ZoneInfo(TIMEZONE),
            ),
            id=f"daily_{hour:02d}_{minute:02d}",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info("زمان ارسال ثبت شد: %s", value)

    scheduler.start()
    logger.info("ربات فعال است. برای توقف Ctrl+C را بزنید.")

    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("ربات متوقف شد.")
