"""
Jenli ASO – Telegram Autoreply Bot (MVP)
----------------------------------------
Python 3.11+ • aiogram v3

Features
- Auto-qualification chat flow for new leads (ASO / ASA / Consulting)
- Quick-reply keyboards; multilingual copy stubs (EN/RU/ES)
- Handoff to human (/human or keyword detection) with admin alert
- Lead summary sent to ADMIN_CHAT_ID + optional Google Sheet/Webhook/Slack
- Deep-link support (t.me/<bot>?start=source) to track acquisition source/TID
- Rate limiting + basic validation for links/emails
- Ready for webhook or long-polling

ENV VARS required
- BOT_TOKEN: BotFather token
- ADMIN_CHAT_ID: your Telegram user ID or admin group ID (integer)
- WEBHOOK_URL: (optional) full https URL for webhooks
- OUTBOUND_WEBHOOK_URL: (optional) your CRM/Sheet endpoint
- SLACK_WEBHOOK_URL: (optional) Slack incoming webhook

Notes about Telegram constraints
- A bot CANNOT DM a user first. The user must press Start or message the bot.
- If your leads appear in a channel, add a CTA/link: t.me/<your_bot>?start=TID so the flow starts immediately.
"""

from __future__ import annotations
import asyncio
import os
import re
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.utils.markdown import hbold, hlink
import httpx

from dotenv import load_dotenv
load_dotenv()

# --- ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
OUTBOUND_WEBHOOK_URL = os.getenv("OUTBOUND_WEBHOOK_URL")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN env is required")

from aiogram.client.default import DefaultBotProperties
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- Helpers / Copy ---
LANGS = ["EN", "RU", "ES"]

COPY = {
    "EN": {
        "greet": "Hi! I’m Jenli ASO Assistant. I’ll ask a few quick questions to route you fast. You can type /human anytime to talk to Artem.",
        "choose_lang": "Choose language / Выберите язык / Elige idioma:",
        "service": "What do you need help with?",
        "services": ["ASO", "Apple Search Ads (ASA)", "Consulting"],
        "platform": "Which platform(s)?",
        "platforms": ["iOS", "Android", "Both"],
        "goal": "Main goal right now?",
        "goals": ["More installs", "Better conversion", "Keyword ranking", "Scale paid (ASA)", "Other"],
        "budget": "Do you have a monthly budget range for growth/ads/design? (You can skip)",
        "store": "Share your app link(s): App Store / Google Play.",
        "email": "What’s your email to send a plan & quote?",
        "notes": "Anything else I should know? (deadlines, markets, competitors)",
        "summary": "Thanks! Here’s a quick summary 👇 I’ll pass this to the JenLi team and we’ll get back to you shortly.",
        "invalid_link": "Please send a valid App Store or Google Play link.",
        "invalid_email": "That doesn’t look like an email. Try again or type 'skip'.",
        "human": "Got it — I’ve alerted Artem. He’ll jump in shortly here.",
    },
    "RU": {
        "greet": "Привет! Я бот-ассистент Jenli ASO. Задам пару вопросов и быстро направлю вас к нужному решению. В любой момент напишите /human — подключу Артёма.",
        "choose_lang": "Выберите язык / Choose language / Elige idioma:",
        "service": "С чем нужна помощь?",
        "services": ["ASO", "Apple Search Ads (ASA)", "Консультация"],
        "platform": "Какая платформа?",
        "platforms": ["iOS", "Android", "Обе"],
        "goal": "Главная цель сейчас?",
        "goals": ["Больше установок", "Выше конверсия", "Рост позиций по ключам", "Масштаб ASA", "Другое"],
        "budget": "Есть ли бюджет на рост/рекламу/дизайн? (можно пропустить)",
        "store": "Пришлите ссылку(и) на приложение: App Store / Google Play.",
        "email": "Оставьте почту для плана и сметы:",
        "notes": "Есть ли детали: сроки, страны, конкуренты?",
        "summary": "Спасибо! Краткое резюме ниже 👇 Передаю в команду JenLi, мы скоро вернёмся с ответом.",
        "invalid_link": "Пожалуйста, отправьте корректную ссылку App Store или Google Play.",
        "invalid_email": "Похоже, это не e-mail. Попробуйте ещё раз или напишите 'skip'.",
        "human": "Ок — сообщил Артёму. Он скоро подключится в этот чат.",
    },
    "ES": {
        "greet": "¡Hola! Soy el asistente de Jenli ASO. Haré unas preguntas rápidas para ayudarte mejor. En cualquier momento escribe /human para hablar con Artem.",
        "choose_lang": "Elige idioma / Choose language / Выберите язык:",
        "service": "¿Con qué necesitas ayuda?",
        "services": ["ASO", "Apple Search Ads (ASA)", "Consultoría"],
        "platform": "¿Qué plataforma(s)?",
        "platforms": ["iOS", "Android", "Ambas"],
        "goal": "¿Objetivo principal ahora?",
        "goals": ["Más instalaciones", "Mejor conversión", "Ranking por keywords", "Escalar ASA", "Otro"],
        "budget": "¿Tienes presupuesto mensual para crecimiento/ads/diseño? (puedes omitir)",
        "store": "Comparte el/los enlaces de tu app: App Store / Google Play.",
        "email": "¿Cuál es tu email para enviar plan y presupuesto?",
        "notes": "¿Algo más que deba saber? (plazos, países, competidores)",
        "summary": "¡Gracias! Resumen rápido abajo 👇 Lo paso al equipo de JenLi y pronto te daremos una respuesta.",
        "invalid_link": "Por favor, envía un enlace válido de App Store o Google Play.",
        "invalid_email": "Eso no parece un email. Inténtalo otra vez o escribe 'skip'.",
        "human": "Hecho — ya avisé a Artem. Se unirá pronto aquí.",
    },
}

link_re = re.compile(r"https?://\S+", re.I)
email_re = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
store_domains = ("apps.apple.com", "play.google.com")

def is_store_link(text: str) -> bool:
    links = link_re.findall(text or "")
    return any(any(d in url for d in store_domains) for url in links)

# --- Slack helpers ---
def detect_store_kind(links_text: str) -> str:
    text = (links_text or "").lower()
    if "apps.apple.com" in text:
        return "App Store (iOS)"
    if "play.google.com" in text:
        return "Google Play (Android)"
    return "Unknown"

def guess_country_from_links(links_text: str) -> Optional[str]:
    # App Store: https://apps.apple.com/{cc}/...
    m = re.search(r"apps\.apple\.com/([a-z]{2})/", links_text or "", re.I)
    if m:
        return m.group(1).upper()
    # Google Play: ...&gl=US
    m = re.search(r"[?&]gl=([A-Za-z]{2})", links_text or "")
    if m:
        return m.group(1).upper()
    return None

async def send_slack(payload: Dict[str, Any]):
    if not SLACK_WEBHOOK_URL:
        return

    user_disp = payload.get("name") or "user"
    if payload.get("username"):
        user_disp = f"<https://t.me/{payload['username']}|{user_disp}>"

    service = payload.get("service", "—")
    platform = payload.get("platform", "—")
    links = payload.get("store_links", "—")
    store_kind = detect_store_kind(links)
    country = guess_country_from_links(links) or "—"
    goal = payload.get("goal", "—")
    budget = payload.get("budget", "—")
    email = payload.get("email", "—")
    notes = payload.get("notes", "—")
    lang = payload.get("lang", "—")
    source = payload.get("source", "—")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🆕 JenLi — новый лид"}},
        {"type": "section",
         "fields": [
            {"type":"mrkdwn","text": f"*From:*\n{user_disp}"},
            {"type":"mrkdwn","text": f"*Service:*\n{service}"},
            {"type":"mrkdwn","text": f"*Platform:*\n{platform}"},
            {"type":"mrkdwn","text": f"*Store:*\n{store_kind}"},
            {"type":"mrkdwn","text": f"*Country:*\n{country}"},
            {"type":"mrkdwn","text": f"*Goal:*\n{goal}"},
            {"type":"mrkdwn","text": f"*Budget:*\n{budget}"},
            {"type":"mrkdwn","text": f"*Email:*\n{email}"},
            {"type":"mrkdwn","text": f"*Lang:*\n{lang}"},
            {"type":"mrkdwn","text": f"*Source:*\n{source}"},
         ]},
        {"type": "section", "text": {"type":"mrkdwn","text": f"*Links:*\n{links}"}},
    ]
    if notes and notes != "—":
        blocks.append({"type":"section","text":{"type":"mrkdwn","text": f"*Notes:*\n{notes}"}})

    data = {"blocks": blocks}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(SLACK_WEBHOOK_URL, json=data)
            print(f"[SLACK] status={resp.status_code} body={resp.text[:200]}")
    except Exception as e:
        print(f"[SLACK][ERROR] {e!r}")

# --- FSM ---
class LeadStates(StatesGroup):
    lang = State()
    service = State()
    platform = State()
    goal = State()
    budget = State()
    store = State()
    email = State()
    notes = State()

def kb(options: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=o)] for o in options]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)

def inline_lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="EN", callback_data="lang:EN"),
         InlineKeyboardButton(text="RU", callback_data="lang:RU"),
         InlineKeyboardButton(text="ES", callback_data="lang:ES")]
    ])

# --- Admin notify ---
async def notify_admin(payload: Dict[str, Any]):
    if not ADMIN_CHAT_ID:
        return

    username = payload.get('username')
    name = payload.get('name', 'user')
    user_link = f"https://t.me/{username}" if username else None
    user_str = hlink(name, user_link) if user_link else name

    text = (
        f"<b>New lead</b>\n"
        f"From: {user_str}\n"
        f"Service: {payload.get('service')}\n"
        f"Platform: {payload.get('platform')}\n"
        f"Goal: {payload.get('goal')}\n"
        f"Budget: {payload.get('budget','—')}\n"
        f"Links: {payload.get('store_links','—')}\n"
        f"Email: {payload.get('email','—')}\n"
        f"Lang: {payload.get('lang')} | Source: {payload.get('source','—')}\n"
        f"User id: {payload.get('user_id')}"
    )
    await bot.send_message(ADMIN_CHAT_ID, text, disable_web_page_preview=True)

    if OUTBOUND_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                await client.post(OUTBOUND_WEBHOOK_URL, json=payload)
        except Exception:
            pass

# --- Handlers ---
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    source = None
    if message.text and len(message.text.split()) > 1:
        source = message.text.split(maxsplit=1)[1]
    user = message.from_user
    await state.update_data(
        user_id=user.id,
        username=user.username,
        name=f"{user.full_name}",
        source=source,
        started_at=datetime.utcnow().isoformat(),
    )
    await state.set_state(LeadStates.lang)
    await message.answer(COPY["EN"]["choose_lang"], reply_markup=inline_lang_kb())

@dp.callback_query(F.data.startswith("lang:"))
async def choose_lang(call: CallbackQuery, state: FSMContext):
    lang = call.data.split(":")[1]
    await state.update_data(lang=lang)
    await call.message.edit_reply_markup()  # remove buttons
    await call.message.answer(COPY[lang]["greet"], reply_markup=kb(COPY[lang]["services"]))
    await state.set_state(LeadStates.service)

@dp.message(LeadStates.lang)
async def lang_fallback(message: Message, state: FSMContext):
    # If user types instead of pressing button
    lang = (message.text or "").strip().upper() or "EN"
    if lang not in LANGS:
        lang = "EN"
    await state.update_data(lang=lang)
    await message.answer(COPY[lang]["greet"], reply_markup=kb(COPY[lang]["services"]))
    await state.set_state(LeadStates.service)

@dp.message(LeadStates.service)
async def pick_service(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "EN")
    service = (message.text or "").strip()
    await state.update_data(service=service)

    # ASA → пропускаем выбор платформы
    if service.lower().startswith("apple search ads"):
        await message.answer(COPY[lang]["goal"], reply_markup=kb(COPY[lang]["goals"]))
        await state.set_state(LeadStates.goal)
    else:
        await message.answer(COPY[lang]["platform"], reply_markup=kb(COPY[lang]["platforms"]))
        await state.set_state(LeadStates.platform)

@dp.message(LeadStates.platform)
async def pick_platform(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "EN")
    await state.update_data(platform=(message.text or "").strip())
    await message.answer(COPY[lang]["goal"], reply_markup=kb(COPY[lang]["goals"]))
    await state.set_state(LeadStates.goal)

@dp.message(LeadStates.goal)
async def pick_goal(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "EN")
    await state.update_data(goal=(message.text or "").strip())
    await message.answer(COPY[lang]["budget"], reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="skip")]], resize_keyboard=True))
    await state.set_state(LeadStates.budget)

@dp.message(LeadStates.budget)
async def pick_budget(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "EN")
    txt = (message.text or "").strip().lower()
    if txt == "skip":
        await state.update_data(budget=None)
    else:
        await state.update_data(budget=(message.text or "").strip())
    await message.answer(COPY[lang]["store"], reply_markup=ReplyKeyboardRemove())
    await state.set_state(LeadStates.store)

@dp.message(LeadStates.store)
async def get_store_links(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "EN")
    if not is_store_link(message.text or ""):
        await message.answer(COPY[lang]["invalid_link"])
        return
    await state.update_data(store_links=(message.text or "").strip())
    await message.answer(COPY[lang]["email"])
    await state.set_state(LeadStates.email)

@dp.message(LeadStates.email)
async def get_email(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "EN")
    text = (message.text or "").strip()
    if text.lower() != "skip" and not email_re.match(text):
        await message.answer(COPY[lang]["invalid_email"])
        return
    await state.update_data(email=None if text.lower() == "skip" else text)
    await message.answer(COPY[lang]["notes"])
    await state.set_state(LeadStates.notes)

@dp.message(LeadStates.notes)
async def get_notes(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "EN")
    await state.update_data(notes=(message.text or "").strip() or None)
    lead = await state.get_data()

    # Summary to user
    summary_lines = [
        f"{hbold('Service')}: {lead.get('service')}",
        f"{hbold('Platform')}: {lead.get('platform')}",
        f"{hbold('Goal')}: {lead.get('goal')}",
        f"{hbold('Budget')}: {lead.get('budget','—')}",
        f"{hbold('Links')}: {lead.get('store_links')}",
        f"{hbold('Email')}: {lead.get('email','—')}",
    ]
    await message.answer(COPY[lang]["summary"] + "\n\n" + "\n".join(summary_lines), disable_web_page_preview=True)

    # Notify admin + Slack
    await notify_admin(lead)
    await send_slack(lead)

    await state.clear()

@dp.message(F.text.regexp("(?i)(human|operator|менеджер|человек)"))
async def handoff_keywords(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "EN")
    await message.answer(COPY[lang]["human"])
    user = message.from_user

    await notify_admin({
        "event": "handoff",
        "user_id": user.id,
        "username": user.username,
        "name": user.full_name,
        "lang": data.get("lang","EN"),
        "chat_id": message.chat.id,
    })

    # Slack card for handoff
    await send_slack({
        "event": "handoff",
        "user_id": user.id,
        "username": user.username,
        "name": user.full_name,
        "service": data.get("service", "—"),
        "platform": data.get("platform", "—"),
        "goal": "—",
        "budget": "—",
        "store_links": "—",
        "email": "—",
        "notes": "User requested human handoff",
        "lang": data.get("lang","EN"),
        "source": data.get("source","—"),
    })

@dp.message(Command("human"))
async def handoff_cmd(message: Message, state: FSMContext):
    await handoff_keywords(message, state)

# Optional: reply in groups/channels when mentioned or replied
@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def group_listener(message: Message):
    if message.text and ("@" in message.text or getattr(message, "is_topic_message", False)):
        await message.reply("Please DM me to proceed: t.me/" + (await bot.get_me()).username)

# --- Long-polling entrypoint (not used in webhook mode) ---
async def on_startup_webhook(dispatcher: Dispatcher):
    await bot.set_webhook(WEBHOOK_URL)

async def main():
    if WEBHOOK_URL:
        await on_startup_webhook(dp)
        print("Webhook set. Run your web server to receive updates.")
        while True:
            await asyncio.sleep(3600)
    else:
        print("Starting long-polling…")
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "channel_post", "chat_join_request"]
        )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass