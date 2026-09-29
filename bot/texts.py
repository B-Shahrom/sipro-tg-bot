"""User-facing strings. Add a new language by adding a dict with the same keys and listing it in LANGUAGES."""

LANGUAGE_NAMES = {"ru": "Русский", "uz": "Oʻzbekcha", "tg": "Тоҷикӣ", "en": "English"}

# Names the AI uses for "reply in <language>".
LANGUAGE_PROMPT_NAMES = {"ru": "Russian", "uz": "Uzbek", "tg": "Tajik", "en": "English"}

RU = {
    # main menu buttons
    "btn_catalog": "🛍 Каталог",
    "btn_builder": "🧩 Собрать ПК",
    "btn_cart": "🛒 Корзина",
    "btn_orders": "📦 Мои заказы",
    "btn_service": "🛠 Гарантия и ремонт",
    "btn_info": "ℹ️ О магазине",
    "btn_manager": "👨‍💼 Менеджер",
    "btn_back": "« Назад",
    "btn_cancel": "✖️ Отмена",
    "btn_skip": "Пропустить",
    "btn_send_phone": "📱 Отправить номер",

    "welcome": (
        "Здравствуйте, {name}! 👋\n\n"
        "Я ассистент магазина <b>{store}</b>. Помогу подобрать комплектующие, мониторы, периферию "
        "или готовый ПК, собрать конфигурацию под ваш бюджет, оформить заказ и узнать его статус.\n\n"
        "Просто напишите вопрос своими словами — например, <i>«нужен монитор для игр до 30 000»</i> "
        "или <i>«подойдёт ли RTX 4070 к моему блоку питания на 550 Вт?»</i> — или воспользуйтесь меню ниже."
    ),
    "choose_language": "Выберите язык / Tilni tanlang / Choose language:",
    "language_set": "Язык установлен: русский.",
    "dialog_reset": "Начали диалог заново. Чем могу помочь?",
    "cancelled": "Отменено. Чем ещё могу помочь?",
    "unknown_error": "Извините, произошла ошибка. Попробуйте ещё раз или нажмите «👨‍💼 Менеджер».",
    "ai_unavailable": "Ассистент сейчас недоступен. Я передал ваш вопрос менеджеру — он скоро ответит.",
    "ai_limit": "Вы достигли дневного лимита сообщений ассистенту. Менеджер ответит вам здесь же — нажмите «👨‍💼 Менеджер».",
    "ai_refusal": "С этим вопросом я помочь не могу. Если нужно — нажмите «👨‍💼 Менеджер», и с вами свяжется сотрудник.",
    "answer_above": "Пожалуйста, ответьте на вопрос выше или нажмите «✖️ Отмена».",
    "unsupported_message": "Пока я понимаю только текст. Опишите вопрос словами или нажмите «👨‍💼 Менеджер», чтобы отправить фото сотруднику.",

    # catalog
    "catalog_title": "Выберите категорию:",
    "catalog_empty": "Каталог пока пуст. Менеджер скоро его заполнит — а пока задайте вопрос в чате.",
    "category_title": "<b>{category}</b> — {total} шт. (стр. {page}/{pages})",
    "in_stock": "✅ В наличии: {stock} шт.",
    "out_of_stock": "⏳ Под заказ",
    "product_not_found": "Товар не найден или снят с продажи.",
    "btn_add_to_cart": "🛒 В корзину",
    "btn_ask_ai": "❓ Спросить ассистента",
    "added_to_cart": "Добавлено в корзину: {name}",
    "ask_about_product": "Расскажи подробнее про {name} (артикул {sku}): для чего подходит, с чем совместим, есть ли альтернативы?",

    # cart & checkout
    "cart_empty": "Корзина пуста. Загляните в «🛍 Каталог» или спросите ассистента.",
    "cart_title": "<b>Ваша корзина:</b>",
    "cart_total": "<b>Итого: {total}</b>",
    "cart_stock_warning": "⚠️ Некоторых позиций нет в нужном количестве — менеджер уточнит сроки поставки.",
    "btn_checkout": "✅ Оформить заказ",
    "btn_clear_cart": "🗑 Очистить",
    "cart_cleared": "Корзина очищена.",
    "checkout_name": "Как к вам обращаться?",
    "checkout_phone": "Отправьте номер телефона кнопкой ниже или напишите его:",
    "checkout_bad_phone": "Не похоже на номер телефона. Напишите номер цифрами, можно с «+» в начале.",
    "checkout_delivery": "Как удобнее получить заказ?",
    "btn_pickup": "🏬 Самовывоз",
    "btn_delivery": "🚚 Доставка",
    "checkout_address": "Укажите адрес доставки:",
    "checkout_comment": "Комментарий к заказу (или нажмите «Пропустить»):",
    "checkout_confirm": "<b>Проверьте заказ:</b>\n\n{summary}\n\nВсё верно?",
    "btn_confirm": "✅ Подтвердить",
    "checkout_done": "Спасибо! Заказ <b>№{id}</b> принят. Менеджер свяжется с вами для подтверждения. Статус — в «📦 Мои заказы».",
    "checkout_cancelled": "Оформление отменено. Товары остались в корзине.",
    "pickup": "Самовывоз",

    # orders
    "orders_empty": "У вас пока нет заказов.",
    "orders_title": "<b>Ваши заказы:</b>",
    "order_line": "№{id} от {date} — {total} — {status}",
    "order_status_changed": "Статус заказа <b>№{id}</b> изменён: {status}",
    "status_new": "🆕 Новый",
    "status_confirmed": "👍 Подтверждён",
    "status_paid": "💳 Оплачен",
    "status_shipped": "🚚 Отправлен / готов к выдаче",
    "status_done": "✔️ Выполнен",
    "status_cancelled": "❌ Отменён",

    # service / warranty
    "service_intro": "Оформим обращение по гарантии или ремонту.\n\nУкажите номер заказа (если есть) или нажмите «Пропустить»:",
    "service_product": "Какое устройство? (модель или описание)",
    "service_problem": "Опишите проблему как можно подробнее: что происходит, когда началось, что уже пробовали.",
    "service_phone": "Номер телефона для связи:",
    "service_done": "Обращение <b>№{id}</b> зарегистрировано. Сервисный специалист свяжется с вами. Фото или видео неисправности можно отправить менеджеру через «👨‍💼 Менеджер».",
    "ticket_status_changed": "Статус обращения <b>№{id}</b>: {status}",
    "tstatus_new": "🆕 Новое",
    "tstatus_in_progress": "🔧 В работе",
    "tstatus_done": "✔️ Выполнено",
    "tstatus_rejected": "❌ Отклонено",

    # PC builder
    "builder_purpose": "Для чего нужен компьютер?",
    "purpose_gaming": "🎮 Игры",
    "purpose_work": "💼 Работа / учёба",
    "purpose_creator": "🎬 Монтаж / стриминг / 3D",
    "purpose_office": "🗂 Офис / дом",
    "builder_budget": "Какой бюджет? Выберите вариант или напишите сумму:",
    "builder_prefs": "Есть пожелания? (бренд, цвет корпуса, нужен ли монитор, конкретные игры/программы). Или нажмите «Пропустить».",
    "builder_bad_budget": "Напишите бюджет одним числом, без букв.",
    "builder_prompt": (
        "Подбери, пожалуйста, сборку ПК.\nНазначение: {purpose}\nБюджет: до {budget}\nПожелания: {prefs}\n"
        "Покажи комплектующие с ценами и итоговой суммой, проверь совместимость и предложи добавить в корзину. "
        "Если есть подходящий готовый ПК — тоже предложи."
    ),
    "no_prefs": "нет",
    "builder_working": "Подбираю конфигурацию… ⏳",
    "cart_compat_title": "<b>Проверка совместимости:</b>",

    # handoff
    "handoff_started": "Соединяю с менеджером. Напишите ваш вопрос — сотрудник ответит здесь же в рабочее время. Можно отправлять фото и файлы.",
    "handoff_active_hint": "Ваше сообщение передано менеджеру.",
    "handoff_ended": "Диалог с менеджером завершён. Снова на связи ассистент 🤖",
    "btn_back_to_ai": "🤖 Вернуться к ассистенту",
    "btn_add_build": "🛒 Добавить сборку в корзину",
    "build_added": "Сборка добавлена в корзину: {count} поз. Откройте «🛒 Корзина», чтобы оформить заказ.",
    "build_expired": "Эта сборка устарела — подберите её заново.",
    "ai_down_alert": "⚠️ ИИ-ассистент недоступен ({reason}). Бот отвечает клиентам в резервном режиме (без ИИ).",
    "ai_up_alert": "✅ ИИ-ассистент снова работает.",
    "manager_reply_prefix": "👨‍💼 <b>Менеджер:</b>",
}

TEXTS: dict[str, dict[str, str]] = {"ru": RU}


def t(key: str, lang: str = "ru", **kwargs) -> str:
    text = TEXTS.get(lang, RU).get(key) or RU[key]
    return text.format(**kwargs) if kwargs else text


def all_variants(key: str) -> set[str]:
    """Every translation of a button label — used to match menu buttons regardless of the user's language."""
    return {texts[key] for texts in TEXTS.values() if key in texts}
