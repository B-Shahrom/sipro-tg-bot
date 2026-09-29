"""Structured view of a product's `specs` string ("Key: value; Key: value").

The offline engine (compatibility checks, PC configurator) relies on these keys. They are documented in the README;
products that lack a key are simply not checked for that rule.
"""

import re
from dataclasses import dataclass
from functools import cached_property

from ..db import Product

CPU = "Процессоры"
MB = "Материнские платы"
RAM = "Оперативная память"
GPU = "Видеокарты"
STORAGE = "Накопители"
PSU = "Блоки питания"
CASE = "Корпуса"
COOLING = "Охлаждение"
MONITOR = "Мониторы"
READY_PC = "Готовые ПК"

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def parse_specs(specs: str) -> dict[str, str]:
    out = {}
    for part in specs.split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            out[key.strip().lower()] = value.strip()
    return out


def first_number(value: str | None) -> float | None:
    if not value:
        return None
    m = _NUM.search(value)
    return float(m.group().replace(",", ".")) if m else None


def _yes(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower().startswith(("да", "yes", "есть"))


def _items(value: str | None) -> set[str]:
    if not value:
        return set()
    return {v.strip().upper() for v in re.split(r"[,/]", value) if v.strip()}


@dataclass(frozen=True, eq=False)
class Part:
    """A product with typed accessors for the specs that matter for compatibility."""

    product: Product

    @cached_property
    def s(self) -> dict[str, str]:
        return parse_specs(self.product.specs)

    @property
    def category(self) -> str:
        return self.product.category

    @property
    def price(self) -> float:
        return self.product.price

    @property
    def name(self) -> str:
        return self.product.name

    # --- CPU / motherboard ---
    @property
    def socket(self) -> str | None:
        v = self.s.get("сокет")
        return v.strip().upper() if v else None

    @property
    def memory_types(self) -> set[str]:
        """DDR generations supported (CPU: 'DDR4/DDR5'; board: 'DDR5, 4 слота, до 192 ГБ')."""
        return set(re.findall(r"DDR\d", self.s.get("память", "").upper()))

    @property
    def tdp(self) -> float | None:
        return first_number(self.s.get("tdp"))

    @property
    def has_igpu(self) -> bool:
        return bool(_yes(self.s.get("встроенная графика")))

    @property
    def boxed_cooler(self) -> bool:
        return bool(_yes(self.s.get("кулер в комплекте")))

    @property
    def form_factor(self) -> str | None:
        v = self.s.get("форм-фактор")
        return v.strip().upper() if v else None

    @property
    def wifi(self) -> bool:
        return bool(_yes(self.s.get("wi-fi")))

    # --- RAM ---
    @property
    def ram_type(self) -> str | None:
        m = re.search(r"DDR\d", self.s.get("тип", "").upper())
        return m.group() if m else None

    @property
    def capacity_gb(self) -> float | None:
        v = self.s.get("объём") or self.s.get("объем")
        n = first_number(v)
        if n is None:
            return None
        return n * 1000 if v and "ТБ" in v.upper() else n

    # --- GPU ---
    @property
    def length_mm(self) -> float | None:
        return first_number(self.s.get("длина"))

    @property
    def recommended_psu(self) -> float | None:
        return first_number(self.s.get("рекомендуемый бп"))

    # --- PSU ---
    @property
    def watts(self) -> float | None:
        return first_number(self.s.get("мощность"))

    @property
    def psu_form_factor(self) -> str:
        return (self.s.get("форм-фактор") or "ATX").strip().upper()

    # --- case ---
    @property
    def case_boards(self) -> set[str]:
        return _items(self.s.get("форм-факторы плат"))

    @property
    def case_psu(self) -> str:
        return (self.s.get("форм-фактор бп") or "ATX").strip().upper()

    @property
    def max_gpu_mm(self) -> float | None:
        return first_number(self.s.get("макс. длина видеокарты"))

    @property
    def max_cooler_mm(self) -> float | None:
        return first_number(self.s.get("макс. высота кулера"))

    @property
    def max_radiator_mm(self) -> float | None:
        return first_number(self.s.get("радиатор")) if self.category == CASE else None

    # --- cooling ---
    @property
    def cooler_kind(self) -> str:
        kind = self.s.get("тип", "").lower()
        if "сжо" in kind:
            return "aio"
        if "термопаст" in kind:
            return "paste"
        return "air"

    @property
    def cooler_height(self) -> float | None:
        return first_number(self.s.get("высота"))

    @property
    def radiator_mm(self) -> float | None:
        return first_number(self.s.get("радиатор")) if self.category == COOLING else None

    @property
    def cooler_sockets(self) -> set[str]:
        return _items(self.s.get("сокеты"))

    @property
    def color(self) -> str:
        return (self.s.get("цвет") or "").lower()

    # --- storage ---
    @property
    def is_nvme(self) -> bool:
        return "nvme" in self.s.get("тип", "").lower()

    # --- ready PC ---
    @property
    def purpose(self) -> str:
        return (self.s.get("назначение") or "").lower()
