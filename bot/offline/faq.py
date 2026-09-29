"""Answers from data/store_info.md: the file is split into "## Section" blocks, questions are matched to sections."""

import re
from pathlib import Path

_COMMENT = re.compile(r"<!--.*?-->", re.S)

# topic -> (words/phrases in the question, words that identify the section title)
TOPICS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "address": (("адрес", "где наход", "где вы", "где магазин", "как добрат", "как проехат", "как найти", "ориентир",
                 "локаци", "парковк"), ("адрес",)),
    "hours": (("час", "график", "время работы", "режим работы", "открыт", "закрыт", "работаете", "до скольки",
               "выходн", "воскресен", "суббот"), ("час", "график", "время")),
    "contacts": (("телефон", "контакт", "позвонить", "номер телефон", "instagram", "инстаграм", "whatsapp", "ватсап",
                  "сайт"), ("контакт",)),
    "payment": (("оплат", "карт", "налич", "перевод", "рассрочк", "кредит", "безнал", "qr", "счет", "счёт"),
                ("оплат",)),
    "delivery": (("доставк", "достав", "курьер", "привез", "самовывоз", "забрать", "отправк", "отправит"),
                 ("доставк",)),
    "assembly": (("стоимость сборки", "сборка стоит", "за сборку", "собираете", "собрать из", "установ", "windows",
                  "виндовс", "винду", "драйвер"), ("сборк",)),
    "warranty": (("гарант",), ("гарант",)),
    "returns": (("возврат", "вернуть", "обмен", "поменять"), ("возврат", "обмен")),
    "tradein": (("трейд", "trade", "скупк", "выкуп", "сдать стар", "в зачет", "в зачёт", "б/у"), ("трейд",)),
}


def load_sections(path: Path) -> tuple[str, dict[str, str]]:
    """(intro text, {section title: body})."""
    if not path.exists():
        return "", {}
    text = _COMMENT.sub("", path.read_text(encoding="utf-8")).strip()
    parts = re.split(r"^##\s+(.+)$", text, flags=re.M)
    intro, sections = parts[0].strip(), {}
    for title, body in zip(parts[1::2], parts[2::2], strict=False):
        sections[title.strip()] = body.strip()
    return intro, sections


def clean_store_info(path: Path) -> str:
    """store_info.md without authoring comments (what customers and the AI see)."""
    if not path.exists():
        return ""
    return _COMMENT.sub("", path.read_text(encoding="utf-8")).strip()


def _matches(norm: str, tokens: list[str], keyword: str) -> bool:
    if " " in keyword or "/" in keyword:
        return keyword in norm
    return any(tok.startswith(keyword) for tok in tokens)


def match_topics(norm: str, tokens: list[str]) -> list[str]:
    return [topic for topic, (keywords, _) in TOPICS.items() if any(_matches(norm, tokens, k) for k in keywords)]


def section_for(topic: str, sections: dict[str, str]) -> tuple[str, str] | None:
    markers = TOPICS[topic][1]
    for title, body in sections.items():
        if any(m in title.lower() for m in markers):
            return title, body
    return None
