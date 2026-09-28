import html
import re

from .db import CartLine, Order, Product, Ticket
from .texts import t

TELEGRAM_LIMIT = 4096


def money(amount: float, currency: str) -> str:
    value = f"{amount:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"{value} {currency}"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def product_card(p: Product, currency: str, lang: str) -> str:
    lines = [f"<b>{esc(p.name)}</b>"]
    if p.brand:
        lines.append(f"Бренд: {esc(p.brand)}")
    lines.append(f"Артикул: <code>{esc(p.sku)}</code>")
    lines.append(f"\n💰 <b>{money(p.price, currency)}</b>")
    lines.append(t("in_stock", lang, stock=p.stock) if p.stock > 0 else t("out_of_stock", lang))
    if p.specs:
        specs = "\n".join(f"• {esc(s.strip())}" for s in p.specs.split(";") if s.strip())
        lines.append(f"\n{specs}")
    if p.description:
        lines.append(f"\n{esc(p.description)}")
    return "\n".join(lines)


def cart_text(lines: list[CartLine], currency: str, lang: str) -> str:
    rows = [t("cart_title", lang), ""]
    for line in lines:
        rows.append(f"• {esc(line.name)} × {line.qty} — {money(line.subtotal, currency)}")
    rows.append("")
    rows.append(t("cart_total", lang, total=money(sum(li.subtotal for li in lines), currency)))
    if any(li.qty > li.stock for li in lines):
        rows.append(t("cart_stock_warning", lang))
    return "\n".join(rows)


def order_status_label(status: str, lang: str) -> str:
    return t(f"status_{status}", lang)


def ticket_status_label(status: str, lang: str) -> str:
    return t(f"tstatus_{status}", lang)


def order_summary(order: Order, currency: str, lang: str = "ru") -> str:
    rows = [f"<b>Заказ №{order.id}</b> — {order_status_label(order.status, lang)}"]
    for item in order.items:
        rows.append(f"• {esc(item.name)} (<code>{esc(item.sku)}</code>) × {item.qty} — {money(item.subtotal, currency)}")
    rows.append(f"<b>Итого: {money(order.total, currency)}</b>")
    rows.append(f"\nИмя: {esc(order.customer_name)}\nТелефон: {esc(order.phone)}")
    if order.delivery:
        rows.append(f"Получение: {esc(order.delivery)}")
    if order.comment:
        rows.append(f"Комментарий: {esc(order.comment)}")
    return "\n".join(rows)


def ticket_summary(ticket: Ticket, lang: str = "ru") -> str:
    rows = [f"<b>Обращение №{ticket.id}</b> — {ticket_status_label(ticket.status, lang)}"]
    if ticket.order_ref:
        rows.append(f"Заказ: {esc(ticket.order_ref)}")
    rows.append(f"Устройство: {esc(ticket.product)}")
    rows.append(f"Проблема: {esc(ticket.problem)}")
    rows.append(f"Телефон: {esc(ticket.phone)}")
    return "\n".join(rows)


def user_link(user_id: int, full_name: str, username: str | None) -> str:
    name = f'<a href="tg://user?id={user_id}">{esc(full_name or str(user_id))}</a>'
    return f"{name} (@{esc(username)})" if username else name


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split long text on paragraph/line boundaries so each part fits in one Telegram message."""
    parts, current = [], ""
    for para in text.split("\n"):
        candidate = f"{current}\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(para) > limit:
            parts.append(para[:limit])
            para = para[limit:]
        current = para
    if current:
        parts.append(current)
    return parts or [""]


_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text))


_PHONE_RE = re.compile(r"^\+?[\d\s\-()]{7,20}$")


def normalize_phone(text: str) -> str | None:
    text = text.strip()
    if not _PHONE_RE.match(text):
        return None
    digits = re.sub(r"\D", "", text)
    if not 7 <= len(digits) <= 15:
        return None
    return f"+{digits}" if text.startswith("+") else digits
