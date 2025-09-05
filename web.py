# web.py — FastAPI вебхук для aiogram v3
import os
from fastapi import FastAPI, Request
from aiogram.types import Update

# импортируем из твоего bot.py готовые объекты
from bot import dp, bot, WEBHOOK_URL

app = FastAPI()

WEBHOOK_PATH = "/telegram/webhook"  # путь приёма апдейтов (можно менять)

@app.on_event("startup")
async def on_startup():
    # снимаем старый вебхук и устанавливаем новый (если задан)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    else:
        print("WARNING: WEBHOOK_URL is not set")

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)  # pydantic v2 / aiogram v3
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/healthz")
async def health():
    return {"ok": True}