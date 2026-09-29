"""Rule-based assistant used when the AI is not configured or not responding.

Understands (Russian): greetings/thanks, "call a manager", store questions (address, hours, delivery, payment,
warranty...), order status, cart, PC builds with a budget, compatibility questions, and product search with
price limits ("монитор 27 до 25к", "видеокарта rtx 4070", "ssd 1 тб").
"""

import re
from dataclasses import dataclass, field

from ..config import Settings
from ..db import Database, Product
from ..formatting import esc, money, order_status_label
from . import faq
from .compat import check, confirmations
from .configurator import PURPOSE_NAMES, Build, configure, min_budget
from .specs import CASE, COOLING, CPU, GPU, MB, MONITOR, PSU, RAM, READY_PC, STORAGE, Part, parse_specs


@dataclass
class OfflineReply:
    text: str
    products: list[Product] = field(default_factory=list)  # shown as buttons that open product cards
    build: Build | None = None  # shown with an "add the whole build to cart" button
    action: str | None = None  # handoff | builder | cart | orders | show_product
    quick: list[str] = field(default_factory=list)  # quick buttons: catalog | builder | manager | service | cart


# ------------------------------------------------------------------ text helpers

def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е").replace(" ", " ")
    text = re.sub(r"[«»\"“”!?,;:()\[\]]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(norm: str) -> list[str]:
    return [t.strip(".") for t in norm.split() if t.strip(".")]


def has(tokens: list[str], *stems: str) -> bool:
    return any(t.startswith(s) for t in tokens for s in stems)


def has_phrase(norm: str, *phrases: str) -> bool:
    return any(p in norm for p in phrases)


_ENDINGS = ("ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ая", "яя", "ую", "юю", "ой", "ей", "ый", "ий",
            "ое", "ее", "ые", "ие", "ов", "ев", "ах", "ях", "ам", "ям", "ом", "ем", "ы", "и", "а", "я", "у", "ю", "е",
            "о")


def stem(word: str) -> str:
    if not re.fullmatch(r"[а-я]+", word) or len(word) < 5:
        return word
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)]
    return word


# ------------------------------------------------------------------ prices

_NUMBER = r"(\d{1,3}(?:[ .]\d{3})+|\d+(?:[.,]\d+)?)"
_MULT = r"(?:\s*(к|k|тыс\w*|т\.р|тр))?"
_UNITS = r"\s*(гб|тб|гц|вт|мм|дюйм|gb|tb|hz|w|мм|шт|ядер|потоков|\")"
_MAX_WORDS = r"до|не дороже|дешевле|меньше|максимум|макс|в пределах|бюджет\w*|за|не более|не больше"
_MIN_WORDS = r"от|дороже|больше|минимум|не меньше|не дешевле"
_ABOUT_WORDS = r"около|примерно|в районе|порядка|где-то|~"
_PRICE_RE = re.compile(rf"(?:({_MAX_WORDS}|{_MIN_WORDS}|{_ABOUT_WORDS})\s*)?{_NUMBER}{_MULT}(?!{_UNITS})(?![\w-])")


def _to_number(raw: str, mult: str | None) -> float:
    value = float(raw.replace(" ", "").replace(",", ".") if raw.count(".") <= 1 and " " not in raw
                  else raw.replace(" ", "").replace(".", ""))
    if mult:
        value *= 1000
    return value


def parse_prices(norm: str) -> tuple[float | None, float | None, str]:
    """(min, max, text without the price phrases). Bare numbers < 10000 are treated as model numbers (RTX 4070)."""
    lo = hi = None
    spans = []
    for m in _PRICE_RE.finditer(norm):
        word, raw, mult = m.group(1), m.group(2), m.group(3)
        value = _to_number(raw, mult)
        if not word and not mult and value < 10000:
            continue
        if not word and mult and float(raw.replace(",", ".")) < 10:
            continue  # "4к", "2k" — screen resolution, not 4000
        if word and not mult and value < 100:
            continue  # "до 27" is a size, not a price
        if word and re.fullmatch(_MIN_WORDS, word):
            lo = value
        elif word and re.fullmatch(_ABOUT_WORDS, word):
            lo, hi = value * 0.8, value * 1.2
        else:
            hi = value
        spans.append(m.span())
    for start, end in reversed(spans):
        norm = norm[:start] + " " + norm[end:]
    return lo, hi, re.sub(r"\s+", " ", norm).strip()


# ------------------------------------------------------------------ categories

CATEGORY_STEMS: list[tuple[str, tuple[str, ...]]] = [
    (READY_PC, ("готов", "системник", "системный", "компьютер", "комп", "пк")),
    (GPU, ("видеокарт", "видюх", "видеоплат", "gpu", "rtx", "gtx", "geforce", "radeon", "джифорс")),
    (CPU, ("процессор", "проц", "cpu", "ryzen", "райзен", "intel", "интел")),
    (MB, ("материн", "мать", "матплат", "плат", "motherboard")),
    (RAM, ("оперативк", "оператив", "озу", "ram", "ddr", "памят")),
    (STORAGE, ("ssd", "hdd", "nvme", "m.2", "накопител", "диск", "жестк", "ссд", "винчестер")),
    (PSU, ("бп", "psu", "блок питания", "блоки питания", "блока питания")),
    (CASE, ("корпус",)),
    (COOLING, ("кулер", "охлажд", "сжо", "водянк", "термопаст", "вентилятор")),
    (MONITOR, ("монитор", "экран", "дисплей", "моник")),
    ("Клавиатуры", ("клавиатур", "клава", "клаву", "keyboard")),
    ("Мыши и коврики", ("мыш", "мышк", "коврик", "mouse")),
    ("Гарнитуры и аудио", ("наушник", "гарнитур", "колонк", "акустик", "headset")),
    ("Веб-камеры и микрофоны", ("веб-камер", "вебкамер", "вебк", "камер", "микрофон", "webcam")),
    ("Сетевое оборудование", ("роутер", "маршрутизатор", "wi-fi", "wifi", "вайфай", "адаптер", "сетев", "кабел")),
    ("ИБП и сетевые фильтры", ("ибп", "бесперебой", "ups", "фильтр", "удлинит")),
]


def detect_categories(norm: str, tokens: list[str]) -> list[str]:
    found = []
    for category, stems in CATEGORY_STEMS:
        for s in stems:
            if (" " in s and s in norm) or (" " not in s and any(t.startswith(s) for t in tokens)):
                found.append(category)
                break
    # "плата" alone could be a GPU ("видеоплата"), "rx 7600" is a GPU, "ddr5" with "плата" is a board.
    if MB in found and GPU in found and not has(tokens, "материн", "мать", "матплат"):
        found.remove(MB)
    if RAM in found and MB in found and not has(tokens, "оператив", "озу", "ram", "памят"):
        found.remove(RAM)
    if READY_PC in found and len(found) > 1 and not has(tokens, "готов", "системник", "системный"):
        found.remove(READY_PC)
    return found


STOPWORDS = {
    "нужен", "нужна", "нужно", "нужны", "надо", "хочу", "хотел", "хотела", "хотим", "ищу", "есть", "ли", "у", "вас",
    "какой", "какая", "какое", "какие", "каких", "посоветуйте", "посоветуй", "подскажите", "подскажи", "для", "и",
    "или", "в", "на", "с", "со", "мне", "нам", "пожалуйста", "пж", "плиз", "купить", "куплю", "сколько", "стоит",
    "стоят", "цена", "цены", "ценой", "недорого", "недорогой", "недорогую", "дешево", "дешевый", "дешевую", "хороший",
    "хорошую", "хорошая", "хорошие", "лучший", "лучшую", "лучшая", "лучше", "самый", "самую", "самая", "норм",
    "нормальный", "нормальную", "что", "то", "это", "а", "по", "же", "бы", "можно", "покажите", "покажи", "показать",
    "дайте", "варианты", "вариант", "наличии", "наличие", "из", "к", "под", "не", "очень", "сейчас", "руб", "рублей",
    "сомони", "сом", "тенге", "сум", "долларов", "₽", "шт", "штук", "модель", "модели", "чтобы", "было", "будет",
    "мой", "моя", "мою", "мое", "моего", "моей", "новый", "новую", "новая", "брать", "взять", "игр", "игры", "игровой",
    "игровую", "игровая", "игровые", "для игр", "тянул", "тянула", "здравствуйте", "привет", "добрый", "день",
}


# Category hints that are also meaningful search words (brands, technologies).
KEEP_AS_KEYWORD = {"rtx", "gtx", "geforce", "radeon", "ryzen", "intel", "nvme", "ssd", "hdd", "m.2", "wi-fi", "wifi"}


def extract_keywords(norm_wo_prices: str, categories: list[str]) -> list[str]:
    cat_stems = [s for c, stems in CATEGORY_STEMS if c in categories for s in stems if s not in KEEP_AS_KEYWORD]
    words = []
    for tok in tokenize(norm_wo_prices):
        if tok in STOPWORDS or len(tok) < 2 and not tok.isdigit():
            continue
        if tok not in KEEP_AS_KEYWORD and any(tok.startswith(s) for s in cat_stems if " " not in s) \
                and not re.search(r"\d", tok):
            continue
        words.append(stem(tok))
    return words


# ------------------------------------------------------------------ product mentions

_MODEL_TOKEN = re.compile(r"[a-zа-я]*\d[\w\-]*", re.I)


def _name_tokens(p: Product) -> set[str]:
    return {t for t in re.split(r"[\s/()+,]+", p.name.lower()) if t}


def find_mentioned(products: list[Product], norm: str, tokens: list[str], categories: list[str],
                   strict: bool = False) -> list[Product]:
    """Products the customer refers to by SKU or model number ("4070 super", "7800x3d", "b650m-a", "ak400").
    strict: skip ambiguous model numbers ("4070" → 4070 SUPER or 4070 Ti SUPER?) instead of guessing."""
    by_sku = {p.sku.lower(): p for p in products}
    found: dict[str, Product] = {}
    for tok in tokens:
        if tok in by_sku:
            found[by_sku[tok].sku] = by_sku[tok]
    text_tokens = set(tokens)
    for tok in tokens:
        if not _MODEL_TOKEN.fullmatch(tok) or tok in by_sku or len(tok) < 3:
            continue
        if re.fullmatch(r"\d+", tok) and len(tok) < 3:
            continue
        candidates = [p for p in products if tok in _name_tokens(p)]
        if not candidates:
            continue

        def score(p: Product) -> tuple:
            overlap = len(_name_tokens(p) & text_tokens)
            return (overlap + (2 if p.category in categories else 0), p.stock > 0, -p.price)

        ranked = sorted(candidates, key=score, reverse=True)
        if strict and len(ranked) > 1 and score(ranked[0])[0] == score(ranked[1])[0]:
            continue
        best = ranked[0]
        found.setdefault(best.sku, best)
    return list(found.values())


# ------------------------------------------------------------------ the assistant

GREETINGS = ("привет", "здравств", "добрый", "доброе", "салам", "ассалом", "салом", "hello", "hi", "хай", "прив",
             "здарова", "здорово")
THANKS = ("спасиб", "благодар", "рахмат", "thanks", "thank", "спс", "сенкс")
HUMAN = ("менеджер", "оператор", "консультант", "человек", "сотрудник", "живой", "живым", "продавц", "админ")
HUMAN_PHRASES = ("позовите", "позвоните мне", "перезвоните", "свяжитесь", "связаться с", "соедините")
DISCOUNT = ("скидк", "торг", "акци", "промокод", "дешевле можно", "уступите", "оптом", "опт ")
PROBLEM = ("сломал", "не работает", "не включается", "не запускается", "брак", "ремонт", "артефакт", "не видит",
           "перегрева", "шумит", "сгорел", "синий экран", "bsod", "отвал", "глючит", "тормозит", "мерцает", "битый")
COMPAT = ("совмест", "подойд", "подход", "потян", "влез", "помест", "встан", "совмещ", "будет работать", "хватит",
          "сочета", "запустит", "пойдет", "пойдёт")
BUILD_PHRASES = ("собрать", "собери", "соберите", "сборку пк", "сборку компьютер", "сборка пк", "сборка компьютер",
                 "подобрать пк", "подберите пк", "подбери пк", "подобрать компьютер", "подберите компьютер",
                 "подбери компьютер", "конфиг", "какой пк", "какой компьютер", "какой комп", "пк для", "компьютер для",
                 "комп для", "пк за", "компьютер за", "комп за", "системник для", "системник за", "сборку для",
                 "сборка для", "сборку за", "сборка за", "пк на", "комп на")
ASSEMBLY_FAQ = ("стоимость сборки", "сборка стоит", "стоит сборка", "за сборку", "собираете ли", "собираете",
                "собрать из моих", "собрать из своих", "соберете из")
PURPOSE_WORDS = {
    "creator": ("монтаж", "видеомонтаж", "стрим", "3d", "блендер", "blender", "рендер", "нейросет", "дизайн",
                "фотошоп", "photoshop", "premiere", "davinci", "after effects"),
    "gaming": ("игр", "гейм", "game", "cs2", "cs", "кс", "dota", "дота", "valorant", "валорант", "warzone", "gta",
               "гта", "fortnite", "pubg", "киберспорт", "cyberpunk", "киберпанк"),
    "work": ("работ", "учеб", "программир", "разработ", "кодинг", "код", "студент", "1с", "бухгалт"),
    "office": ("офис", "документ", "интернет", "браузер", "дом", "домашн", "ребенк", "ребенок", "родител", "касс",
               "ютуб", "youtube", "фильм"),
}


def detect_purpose(norm: str, tokens: list[str]) -> str | None:
    for purpose in ("creator", "gaming", "work", "office"):
        for w in PURPOSE_WORDS[purpose]:
            if (" " in w and w in norm) or any(t.startswith(w) for t in tokens):
                return purpose
    return None


def _short_specs(p: Product, n: int = 3) -> str:
    values = [v for v in parse_specs(p.specs).values()][:n]
    return " · ".join(v[:30] for v in values)


def product_lines(products: list[Product], currency: str) -> str:
    rows = []
    for i, p in enumerate(products, 1):
        stock = "✅" if p.stock > 0 else "⏳ под заказ"
        rows.append(f"{i}. <b>{esc(p.name)}</b> — {money(p.price, currency)} {stock}")
        specs = _short_specs(p)
        if specs:
            rows.append(f"    <i>{esc(specs)}</i>")
    return "\n".join(rows)


def build_text(build: Build, currency: str) -> str:
    from .configurator import ROLE_NAMES

    rows = [f"🧩 <b>Сборка для {PURPOSE_NAMES[build.purpose]}</b> — бюджет до {money(build.budget, currency)}", ""]
    for p in build.parts:
        role = ROLE_NAMES.get(p.category, p.category)
        rows.append(f"• {role}: {esc(p.name)} — <b>{money(p.price, currency)}</b>")
    rows.append("")
    rows.append(f"<b>Итого: {money(build.total, currency)}</b>")
    ok = confirmations(build.parts)
    if ok:
        rows.append("\n✅ <b>Совместимость проверена:</b>\n" + "\n".join(f"• {esc(line)}" for line in ok))
    for note in build.notes:
        rows.append(esc(note))
    if build.ready_pc:
        rows.append(f"\n💡 Есть и готовый вариант: <b>{esc(build.ready_pc.name)}</b> — "
                    f"{money(build.ready_pc.price, currency)} (уже собран и протестирован).")
    rows.append("\nНажмите «🛒 Добавить сборку в корзину» или откройте любой компонент, чтобы заменить его.")
    return "\n".join(rows)


class OfflineAssistant:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    @property
    def currency(self) -> str:
        return self.settings.currency

    def sections(self) -> dict[str, str]:
        return faq.load_sections(self.settings.store_info_path)[1]

    # -------------------------------------------------------------- entry point

    async def reply(self, user_id: int, text: str, degraded: bool = False) -> OfflineReply:
        norm = normalize(text)
        tokens = tokenize(norm)
        if not tokens:
            return self._unknown(degraded)

        if has(tokens, *HUMAN) or has_phrase(norm, *HUMAN_PHRASES):
            return OfflineReply("Соединяю с менеджером 👨‍💼", action="handoff")
        if has(tokens, *DISCOUNT) or has_phrase(norm, *DISCOUNT):
            return OfflineReply("Скидки, акции и оптовые цены подскажет менеджер — передаю ему ваш вопрос.",
                                action="handoff")
        if len(tokens) <= 4 and has(tokens, *THANKS):
            return OfflineReply("Пожалуйста! Если будут вопросы — пишите 🙂")
        if len(tokens) <= 4 and has(tokens, *GREETINGS) and not detect_categories(norm, tokens):
            return OfflineReply(
                "Здравствуйте! 👋 Помогу подобрать технику. Напишите, что ищете — например, "
                "<i>«монитор 27 дюймов до 25000»</i>, <i>«собрать ПК для игр за 100000»</i> или "
                "<i>«где вы находитесь?»</i>.",
                quick=["catalog", "builder"],
            )

        order_reply = await self._orders(user_id, norm, tokens)
        if order_reply:
            return order_reply
        if has(tokens, "корзин"):
            return OfflineReply("Открываю корзину 🛒", action="cart")
        if has_phrase(norm, "как заказать", "как оформить", "как купить", "хочу заказать", "оформить заказ"):
            return OfflineReply(
                "Чтобы оформить заказ: найдите товар в «🛍 Каталог» (или спросите меня), нажмите «🛒 В корзину», "
                "затем «🛒 Корзина» → «✅ Оформить заказ». Менеджер подтвердит заказ и свяжется с вами.",
                quick=["catalog", "cart"],
            )

        if has_phrase(norm, *PROBLEM) or (has(tokens, "гарант") and has(tokens, "ремонт", "сдать", "обратит")):
            section = faq.section_for("warranty", self.sections())
            body = f"\n\n<b>{esc(section[0])}</b>\n{esc(section[1])}" if section else ""
            return OfflineReply(
                "Сочувствую, что возникла проблема 🙁 Оформите обращение — сервисный специалист свяжется с вами."
                + body, quick=["service", "manager"])

        if has_phrase(norm, *ASSEMBLY_FAQ):
            answer = self._faq(["assembly"])
            if answer:
                return answer

        mentioned_all = await self.db.all_products()
        categories = detect_categories(norm, tokens)
        mentioned = find_mentioned(mentioned_all, norm, tokens, categories)

        if has(tokens, *COMPAT) or has_phrase(norm, *COMPAT):
            compat_reply = self._compat(norm, mentioned, mentioned_all)
            if compat_reply:
                return compat_reply

        if (has_phrase(norm, *BUILD_PHRASES) or (has(tokens, "сборк") and not has(tokens, "готов"))) \
                and not has(tokens, "готов"):
            return await self._build(norm, tokens)

        topics = faq.match_topics(norm, tokens)
        if topics and not (categories and not has(tokens, "гарант", "доставк", "оплат", "рассрочк")):
            answer = self._faq(topics[:2])
            if answer:
                return answer

        exact = find_mentioned(mentioned_all, norm, tokens, categories, strict=True)
        if len(exact) == 1 and (not categories or (exact[0].category in categories and len(tokens) <= 4)):
            return OfflineReply("Вот этот товар:", products=exact, action="show_product")

        search = await self._search(norm, tokens, categories)
        if search:
            return search
        if topics:
            answer = self._faq(topics[:2])
            if answer:
                return answer
        return self._unknown(degraded)

    # -------------------------------------------------------------- intents

    def _unknown(self, degraded: bool) -> OfflineReply:
        text = (
            "Не совсем понял вопрос 🙈 Я умею:\n"
            "• искать товары — <i>«видеокарта до 40000»</i>, <i>«ssd 1 тб»</i>\n"
            "• собирать ПК — <i>«собрать ПК для игр за 100000»</i>\n"
            "• проверять совместимость — <i>«подойдёт ли 7800x3d к b650m-a?»</i>\n"
            "• отвечать про адрес, доставку, оплату, гарантию и статус заказа\n\n"
            "Или позовите менеджера — он ответит здесь же."
        )
        if degraded:
            text += "\n\n<i>Сейчас я работаю в упрощённом режиме, поэтому понимаю только простые запросы.</i>"
        return OfflineReply(text, quick=["catalog", "builder", "manager"])

    def _faq(self, topics: list[str]) -> OfflineReply | None:
        sections = self.sections()
        parts = []
        for topic in topics:
            found = faq.section_for(topic, sections)
            if found:
                parts.append(f"<b>{esc(found[0])}</b>\n{esc(found[1])}")
        if not parts:
            return None
        quick = ["service"] if "warranty" in topics else []
        return OfflineReply("\n\n".join(parts), quick=quick + ["manager"])

    async def _orders(self, user_id: int, norm: str, tokens: list[str]) -> OfflineReply | None:
        wants_status = has(tokens, "заказ") and not has(tokens, "заказат", "заказыва") and (
            has(tokens, "статус", "где", "мой", "мои", "когда", "номер", "состояни", "отслед", "пришел", "готов")
            or re.search(r"(№|#|номер\s*)\s*\d+|заказ\w*\s+\d+", norm))
        if not wants_status and not has_phrase(norm, "мои заказы", "статус заказа"):
            return None
        m = re.search(r"(?:№|#|номер|заказ\w*)\s*(\d{1,7})", norm)
        if m:
            order = await self.db.get_order(int(m.group(1)))
            if order and order.user_id == user_id:
                items = "\n".join(f"• {esc(i.name)} × {i.qty}" for i in order.items)
                return OfflineReply(
                    f"Заказ <b>№{order.id}</b> от {order.created_at[:10]}: {order_status_label(order.status, 'ru')}\n"
                    f"{items}\n<b>Итого: {money(order.total, self.currency)}</b>",
                    quick=["manager"])
            return OfflineReply("Не нашёл такой заказ среди ваших. Вот все ваши заказы:", action="orders")
        return OfflineReply("Вот ваши заказы:", action="orders")

    def _compat(self, norm: str, mentioned: list[Product], catalog: list[Product]) -> OfflineReply | None:
        watts = re.search(r"(\d{3,4})\s*(?:вт|w|ватт)", norm)
        gpus = [p for p in mentioned if p.category == GPU]
        lines = []
        if watts and gpus and not any(p.category == PSU for p in mentioned):
            w = float(watts.group(1))
            gpu = Part(gpus[0])
            need = gpu.recommended_psu
            if need:
                verdict = "✅ хватит" if w >= need else "❌ маловато"
                lines.append(f"{verdict}: для {esc(gpu.name)} рекомендуется блок питания от {need:.0f} Вт, "
                             f"у вас {w:.0f} Вт.")
                if w < need:
                    psus = sorted((p for p in catalog if p.category == PSU and p.stock > 0
                                   and (Part(p).watts or 0) >= need), key=lambda p: p.price)[:2]
                    if psus:
                        lines.append("Подойдут, например:")
                        return OfflineReply("\n".join(lines), products=psus)
                return OfflineReply("\n".join(lines), products=gpus[:1])
        if len(mentioned) < 2:
            return None
        issues = check(mentioned)
        names = ", ".join(esc(p.name) for p in mentioned)
        if issues:
            text = f"Проверил: {names}\n\n" + "\n".join(esc(str(i)) for i in issues)
            errors = [i for i in issues if i.level == "error"]
            text += "\n\n" + ("Такое сочетание работать не будет или не рекомендуется." if errors else
                              "В целом совместимы, но обратите внимание на замечания.")
        else:
            ok = confirmations(mentioned)
            text = f"✅ Совместимы: {names}"
            if ok:
                text += "\n\n" + "\n".join(f"• {esc(line)}" for line in ok)
        return OfflineReply(text, products=mentioned[:4], quick=["manager"])

    async def _build(self, norm: str, tokens: list[str]) -> OfflineReply:
        lo, hi, _ = parse_prices(norm)
        budget = hi or (lo * 1.2 if lo else None)
        purpose = detect_purpose(norm, tokens)
        if not budget:
            return OfflineReply("Давайте подберём! Ответьте на пару вопросов 👇", action="builder")
        return await self.build(purpose or "gaming", budget, norm, assumed_purpose=purpose is None)

    async def build(self, purpose: str, budget: float, prefs: str = "", assumed_purpose: bool = False) -> OfflineReply:
        build = await configure(self.db, purpose, budget, prefs)
        if not build or not build.parts:
            cheapest = await min_budget(self.db, purpose)
            text = f"На {money(budget, self.currency)} собрать ПК для {PURPOSE_NAMES.get(purpose, 'игр')} " \
                   f"из наличия, к сожалению, не получится."
            if cheapest:
                text += f" Минимальный бюджет сейчас — около {money(round(cheapest, -2), self.currency)}."
            if build and build.ready_pc:
                text += f"\n\nНо есть готовый ПК: <b>{esc(build.ready_pc.name)}</b> — " \
                        f"{money(build.ready_pc.price, self.currency)}."
                return OfflineReply(text, products=[build.ready_pc], quick=["manager"])
            return OfflineReply(text, quick=["catalog", "manager"])
        text = build_text(build, self.currency)
        if assumed_purpose:
            text = "Подобрал игровой вариант. Если ПК нужен для другого (работа, монтаж, офис) — напишите.\n\n" + text
        return OfflineReply(text, products=build.parts, build=build)

    async def _search(self, norm: str, tokens: list[str], categories: list[str]) -> OfflineReply | None:
        lo, hi, rest = parse_prices(norm)
        keywords = extract_keywords(rest, categories)
        cats = categories or [None]
        purpose = detect_purpose(norm, tokens)
        attempts = [keywords]
        # Relax: drop plain words first (keep model numbers), then everything.
        with_digits = [k for k in keywords if re.search(r"\d", k)]
        if with_digits != keywords:
            attempts.append(with_digits)
        if keywords:
            attempts.append([])
        if not categories and not keywords:
            if lo is None and hi is None:
                return None
        results: list[Product] = []
        used_keywords: list[str] = []
        for kw in attempts:
            if not kw and not categories:
                continue
            for cat in cats:
                results += await self.db.search_products(" ".join(kw), cat, lo, hi, limit=40)
            if results:
                used_keywords = kw
                break
        if not results:
            if categories:
                where = f" в категории «{esc(categories[0])}»" if categories else ""
                price = " в этом ценовом диапазоне" if lo or hi else ""
                return OfflineReply(f"К сожалению, не нашёл подходящих товаров{where}{price}. "
                                    "Посмотрите каталог или спросите менеджера — возможно, привезём под заказ.",
                                    quick=["catalog", "manager"])
            return None

        results = self._refine(results, norm, tokens, purpose)
        results.sort(key=lambda p: (p.stock <= 0, -p.price if hi else p.price))
        shown = results[:6]
        if len(results) == 1:
            return OfflineReply("Вот что нашёл:", products=shown, action="show_product")

        head = "Нашёл" if used_keywords == keywords else "Точных совпадений нет, вот похожие варианты"
        cat_txt = f" — {esc(categories[0].lower())}" if len(categories) == 1 else ""
        price_txt = ""
        if hi and lo:
            price_txt = f" от {money(lo, self.currency)} до {money(hi, self.currency)}"
        elif hi:
            price_txt = f" до {money(hi, self.currency)}"
        elif lo:
            price_txt = f" от {money(lo, self.currency)}"
        more = f"\n\nВсего подходит: {len(results)}. Уточните запрос, чтобы сузить выбор." if len(results) > 6 else ""
        text = f"{head}{cat_txt}{price_txt}:\n\n{product_lines(shown, self.currency)}{more}\n\n" \
               "Нажмите на товар, чтобы открыть карточку и добавить в корзину."
        return OfflineReply(text, products=shown)

    def _refine(self, results: list[Product], norm: str, tokens: list[str], purpose: str | None) -> list[Product]:
        """Soft filters that narrow results only when something matches."""
        seen, unique = set(), []
        for p in results:
            if p.sku not in seen:
                seen.add(p.sku)
                unique.append(p)
        results = unique

        def narrow(pred):
            nonlocal results
            filtered = [p for p in results if pred(p)]
            if filtered:
                results = filtered

        monitors = all(p.category == MONITOR for p in results)
        if monitors:
            if purpose == "gaming":
                narrow(lambda p: (Part(p).s.get("частота") or "0").split()[0].isdigit()
                       and int((Part(p).s.get("частота") or "0").split()[0]) >= 144)
            if has(tokens, "4k", "4к", "uhd"):
                narrow(lambda p: "3840" in p.specs)
            elif has(tokens, "2k", "2к", "qhd", "1440"):
                narrow(lambda p: "2560" in p.specs)
            elif has(tokens, "fullhd", "fhd", "1080") or has_phrase(norm, "full hd"):
                narrow(lambda p: "1920" in p.specs)
        if all(p.category == READY_PC for p in results) and purpose:
            markers = {"gaming": "игр", "creator": "монтаж", "work": "работ", "office": "офис"}
            narrow(lambda p: markers[purpose] in Part(p).purpose)
        if has(tokens, "беспровод", "wireless"):
            narrow(lambda p: "беспровод" in p.specs.lower() or "wireless" in p.name.lower())
        if has(tokens, "бел", "white"):
            narrow(lambda p: "бел" in (p.specs + p.name).lower() or "white" in p.name.lower())
        if has(tokens, "механич"):
            narrow(lambda p: "механич" in p.specs.lower())
        return results

    # -------------------------------------------------------------- product details ("ask about product")

    async def describe(self, sku: str) -> OfflineReply | None:
        p = await self.db.get_product(sku)
        if not p or not p.active:
            return None
        part = Part(p)
        all_products = await self.db.all_products()
        lines = [f"<b>{esc(p.name)}</b> — {money(p.price, self.currency)}"]
        related: list[Product] = []

        def cat(name):
            return [Part(x) for x in all_products if x.category == name and x.stock > 0]

        if p.category == CPU:
            boards = [b for b in cat(MB) if b.socket == part.socket
                      and (not part.memory_types or part.memory_types & b.memory_types)]
            lines.append(f"Сокет {part.socket}, память {'/'.join(sorted(part.memory_types)) or '—'}.")
            lines.append("Кулер в комплекте ✅" if part.boxed_cooler else "Кулера в комплекте нет — понадобится кулер.")
            if not part.has_igpu:
                lines.append("Встроенной графики нет — нужна видеокарта.")
            if boards:
                lines.append("\nПодходящие материнские платы:")
                related += [b.product for b in sorted(boards, key=lambda b: b.price)[:3]]
            if not part.boxed_cooler:
                coolers = [c for c in cat(COOLING) if c.cooler_kind == "air" and part.socket in c.cooler_sockets
                           and (c.tdp or 0) >= (part.tdp or 0)]
                related += [c.product for c in sorted(coolers, key=lambda c: c.price)[:2]]
        elif p.category == MB:
            cpus = [c for c in cat(CPU) if c.socket == part.socket
                    and (not c.memory_types or c.memory_types & part.memory_types)]
            rams = [r for r in cat(RAM) if r.ram_type in part.memory_types]
            lines.append(f"Сокет {part.socket}, формат {part.form_factor}, память "
                         f"{'/'.join(sorted(part.memory_types))}.")
            lines.append("\nПодходящие процессоры и память:")
            related += [c.product for c in sorted(cpus, key=lambda c: c.price)[:3]]
            related += [r.product for r in sorted(rams, key=lambda r: r.price)[:2]]
        elif p.category == GPU:
            need = part.recommended_psu or 0
            lines.append(f"Длина {part.length_mm:.0f} мм, рекомендуемый блок питания — от {need:.0f} Вт."
                         if part.length_mm else "")
            psus = [x for x in cat(PSU) if (x.watts or 0) >= need and x.psu_form_factor == "ATX"]
            cases = [c for c in cat(CASE) if not part.length_mm or (c.max_gpu_mm or 0) >= part.length_mm]
            lines.append("\nПодойдут блоки питания и корпуса:")
            related += [x.product for x in sorted(psus, key=lambda x: x.price)[:2]]
            related += [c.product for c in sorted(cases, key=lambda c: c.price)[:2]]
        elif p.category == RAM:
            boards = [b for b in cat(MB) if part.ram_type in b.memory_types]
            lines.append(f"Тип {part.ram_type} — подходит к платам с поддержкой {part.ram_type}:")
            related += [b.product for b in sorted(boards, key=lambda b: b.price)[:3]]
        elif p.category == PSU:
            gpus = [g for g in cat(GPU) if (g.recommended_psu or 0) <= (part.watts or 0)]
            lines.append(f"Мощность {part.watts:.0f} Вт. Потянет, например:" if part.watts else "")
            related += [g.product for g in sorted(gpus, key=lambda g: -g.price)[:3]]
        elif p.category == CASE:
            lines.append(f"Платы: {', '.join(sorted(part.case_boards))}; видеокарта до {part.max_gpu_mm:.0f} мм; "
                         f"кулер до {part.max_cooler_mm:.0f} мм." if part.max_gpu_mm and part.max_cooler_mm else "")

        similar = sorted((x for x in all_products if x.category == p.category and x.sku != p.sku
                          and abs(x.price - p.price) <= p.price * 0.3 and x.stock > 0),
                         key=lambda x: abs(x.price - p.price))[:3]
        if similar:
            lines.append("\nПохожие по цене альтернативы — в кнопках ниже.")
        if p.description:
            lines.insert(1, esc(p.description))
        text = "\n".join(line for line in lines if line)
        return OfflineReply(text, products=(related + similar)[:8], quick=["manager"])
