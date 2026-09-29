"""Rule-based PC configurator: picks a compatible build from the catalog within a budget.

Approach: try every CPU × GPU pair, complete each with the cheapest compatible board, RAM, SSD, case, cooler and
PSU, keep the best-scoring build that fits the budget, then spend what's left on RAM/SSD upgrades.
"""

from dataclasses import dataclass, field

from ..db import Database, Product
from .compat import check, compatible_ram, cooler_fits_cpu, fits_case, psu_needed
from .specs import CASE, COOLING, CPU, GPU, MB, PSU, RAM, READY_PC, STORAGE, Part

PURPOSES = ("gaming", "work", "creator", "office")
PURPOSE_NAMES = {"gaming": "игр", "work": "работы и учёбы", "creator": "монтажа, стриминга и 3D",
                 "office": "офиса и дома"}
# What a ready-built PC's "Назначение" must mention to be suggested for a purpose.
PURPOSE_READY_MARKERS = {"gaming": ("игр",), "work": ("работ", "учёб", "офис"), "creator": ("монтаж", "3d", "стрим"),
                         "office": ("офис", "учёб")}
TARGET_RAM_GB = {"gaming": 32, "work": 32, "creator": 64, "office": 16}
TARGET_SSD_GB = {"gaming": 1000, "work": 1000, "creator": 2000, "office": 500}
ENTRY_CHIPSETS = {"A520", "A620", "H610"}
# Budget share (of the whole build) above which "nicer" cases/PSUs are preferred over the cheapest ones.
CASE_SHARE, PSU_SHARE = 0.035, 0.05


def minimums(purpose: str, rich: bool) -> tuple[float, float]:
    """(RAM GB, SSD GB) a build must have. `rich`: the budget is well above the cheapest possible build
    (relative, so it works in any currency)."""
    ram = {"gaming": 32 if rich else 16, "work": 32 if rich else 16, "creator": 64 if rich else 32,
           "office": 16}[purpose]
    ssd = {"gaming": 1000 if rich else 500, "work": 1000 if rich else 500, "creator": 2000 if rich else 1000,
           "office": 500}[purpose]
    return ram, ssd


ROLE_NAMES = {CPU: "Процессор", MB: "Материнская плата", RAM: "Память", GPU: "Видеокарта", STORAGE: "Накопитель",
              PSU: "Блок питания", CASE: "Корпус", COOLING: "Кулер"}


@dataclass
class Build:
    purpose: str
    budget: float
    parts: list[Product]
    notes: list[str] = field(default_factory=list)
    ready_pc: Product | None = None

    @property
    def total(self) -> float:
        return sum(p.price for p in self.parts)


@dataclass
class Prefs:
    brand: str | None = None  # "AMD" | "INTEL"
    white: bool = False
    wifi: bool = False
    compact: bool = False

    @classmethod
    def parse(cls, text: str) -> "Prefs":
        t = (text or "").lower()
        brand = None
        if any(w in t for w in ("amd", "ryzen", "райзен", "амд")):
            brand = "AMD"
        if any(w in t for w in ("intel", "интел", "core i")):
            brand = None if brand else "INTEL"
        return cls(
            brand=brand,
            white="бел" in t or "white" in t,
            wifi="wi-fi" in t or "wifi" in t or "вайфай" in t or "вай-фай" in t,
            compact="компакт" in t or "маленьк" in t or "itx" in t,
        )


def _cheapest(options: list[Part], pred=lambda p: True, prefer=lambda p: False) -> Part | None:
    fitting = [o for o in options if pred(o)]
    if not fitting:
        return None
    preferred = [o for o in fitting if prefer(o)]
    return min(preferred or fitting, key=lambda o: o.price)


def _balanced(purpose: str, cpu: Part, gpu: Part | None) -> bool:
    """Avoid bottlenecks: a weak CPU with a flagship GPU, or the other way round."""
    if gpu is None:
        return True
    if purpose == "gaming":
        return 0.25 * gpu.price <= cpu.price <= 1.0 * gpu.price
    if purpose == "creator":
        return 0.3 * gpu.price <= cpu.price <= 2.5 * gpu.price
    return True


def _score(purpose: str, cpu: Part, gpu: Part | None, total: float, budget: float) -> float:
    g = gpu.price if gpu else 0
    if purpose == "gaming":
        return g * 3 + cpu.price * 1.4 + total * 0.1
    if purpose == "creator":
        return cpu.price * 2 + g * 1.6 + total * 0.1
    if purpose == "work":
        return cpu.price * 2 + g * 0.05 - total * 0.3
    return -total + (cpu.price * 0.3)  # office: cheapest sensible build


class Catalog:
    def __init__(self, products: list[Product]):
        in_stock = [p for p in products if p.stock > 0]
        self.parts: dict[str, list[Part]] = {}
        for p in in_stock:
            self.parts.setdefault(p.category, []).append(Part(p))
        self.all_ready = [Part(p) for p in products if p.category == READY_PC]

    def get(self, cat: str) -> list[Part]:
        return self.parts.get(cat, [])


def _complete(cat: Catalog, purpose: str, cpu: Part, gpu: Part | None, prefs: Prefs,
              budget: float = 0, rich: bool = False) -> list[Part] | None:
    """Cheapest sensible compatible set of the remaining parts for a CPU/GPU pair, or None.
    budget=0 means "absolute cheapest" (no quality preferences)."""
    min_ram, min_ssd = minimums(purpose, rich)
    boards = [mb for mb in cat.get(MB) if mb.socket == cpu.socket
              and (not cpu.memory_types or cpu.memory_types & mb.memory_types)]
    if prefs.wifi:
        boards = [mb for mb in boards if mb.wifi] or boards
    if prefs.compact:
        boards = [mb for mb in boards if mb.form_factor == "MINI-ITX"] or boards
    if budget and ((gpu and cpu.price + gpu.price > budget * 0.45) or (cpu.tdp or 0) >= 105):
        # Serious builds and hot CPUs deserve more than an entry-level board (weak VRM).
        boards = [mb for mb in boards if (mb.s.get("чипсет") or "").upper() not in ENTRY_CHIPSETS] or boards
    best, best_total = None, None
    for mb in sorted(boards, key=lambda b: b.price)[:4]:
        ram = _cheapest(compatible_ram(mb, cat.get(RAM)),
                        lambda r: (r.capacity_gb or 0) >= min_ram,
                        prefer=lambda r: prefs.white and "бел" in (r.color + r.name.lower()))
        ssd = _cheapest(cat.get(STORAGE), lambda s: s.is_nvme and (s.capacity_gb or 0) >= min_ssd)
        if not ram or not ssd:
            continue
        # Cooler first (its height constrains the case).
        cooler = None
        if not cpu.boxed_cooler:
            cooler = _cheapest([c for c in cat.get(COOLING) if c.cooler_kind == "air"],
                               lambda c: cooler_fits_cpu(c, cpu))
            if not cooler:
                cooler = _cheapest([c for c in cat.get(COOLING) if c.cooler_kind == "aio"],
                                   lambda c: cooler_fits_cpu(c, cpu))
            if not cooler:
                continue
        cases = [c for c in cat.get(CASE) if fits_case(c, mb, gpu, cooler)]
        if prefs.white:
            cases = [c for c in cases if "бел" in c.color] or cases
        if prefs.compact:
            cases = [c for c in cases if c.case_boards == {"MINI-ITX"}] or cases
        case = _cheapest(cases, prefer=lambda c: c.price >= budget * CASE_SHARE)
        if not case:
            continue
        need = psu_needed(cpu, gpu)
        sfx_only = case.case_psu == "SFX"
        psu = _cheapest([p for p in cat.get(PSU) if (p.watts or 0) >= need
                         and (not sfx_only or p.psu_form_factor == "SFX")],
                        prefer=lambda p: p.price >= budget * PSU_SHARE)
        if not psu:
            continue
        parts = [cpu, mb, ram, gpu, ssd, psu, case, cooler]
        parts = [p for p in parts if p is not None]
        total = sum(p.price for p in parts)
        if best_total is None or total < best_total:
            best, best_total = parts, total
    return best


def _upgrade(cat: Catalog, parts: list[Part], purpose: str, budget: float) -> list[Part]:
    """Spend leftover budget on more RAM, then a bigger SSD."""
    by_cat = {p.category: p for p in parts}
    mb = by_cat[MB]
    for category, target, options in (
        (RAM, TARGET_RAM_GB[purpose], compatible_ram(mb, cat.get(RAM))),
        (STORAGE, TARGET_SSD_GB[purpose], [s for s in cat.get(STORAGE) if s.is_nvme]),
    ):
        current = by_cat[category]
        leftover = budget - sum(p.price for p in by_cat.values())
        better = [o for o in options if (current.capacity_gb or 0) < (o.capacity_gb or 0) <= target
                  and o.price - current.price <= leftover]
        if better:
            by_cat[category] = max(better, key=lambda o: ((o.capacity_gb or 0), -o.price))
    return [by_cat[p.category] for p in parts]


def _ready_pc(cat: Catalog, purpose: str, budget: float) -> Product | None:
    markers = PURPOSE_READY_MARKERS[purpose]
    fitting = [p for p in cat.all_ready if p.price <= budget * 1.05 and any(m in p.purpose for m in markers)]
    return max(fitting, key=lambda p: p.price).product if fitting else None


async def configure(db: Database, purpose: str, budget: float, prefs_text: str = "") -> Build | None:
    if purpose not in PURPOSES:
        purpose = "gaming"
    prefs = Prefs.parse(prefs_text)
    cat = Catalog(await db.all_products())

    cpus = cat.get(CPU)
    if prefs.brand:
        cpus = [c for c in cpus if c.product.brand.upper() == prefs.brand] or cpus
    if prefs.compact:
        itx_sockets = {mb.socket for mb in cat.get(MB) if mb.form_factor == "MINI-ITX"}
        cpus = [c for c in cpus if c.socket in itx_sockets] or cpus
    gpus: list[Part | None] = list(cat.get(GPU))
    if purpose in ("office", "work"):
        gpus = [None] + gpus
    cheapest = await min_budget(db, purpose, cat)
    rich = bool(cheapest) and budget >= cheapest * 1.6

    best, best_score = None, None
    for cpu in cpus:
        for gpu in gpus:
            if gpu is None and not cpu.has_igpu:
                continue
            if purpose == "office" and gpu is not None:
                continue
            if not _balanced(purpose, cpu, gpu) or cpu.price + (gpu.price if gpu else 0) > budget * 0.8:
                continue
            parts = _complete(cat, purpose, cpu, gpu, prefs, budget, rich)
            if not parts:
                continue
            total = sum(p.price for p in parts)
            if total > budget:
                continue
            score = _score(purpose, cpu, gpu, total, budget)
            if best_score is None or score > best_score:
                best, best_score = parts, score

    ready = _ready_pc(cat, purpose, budget)
    if not best:
        return Build(purpose, budget, [], ready_pc=ready) if ready else None
    best = _upgrade(cat, best, purpose, budget)
    products = [p.product for p in best]
    notes = [str(issue) for issue in check(products)]  # should be empty; surfaced if the catalog data is odd
    if sum(p.price for p in products) < budget * 0.7:
        notes.append("💡 Это самая мощная сборка из того, что сейчас есть в наличии — остаток бюджета можно "
                     "потратить на монитор или периферию.")
    return Build(purpose, budget, products, notes=notes, ready_pc=ready)


async def min_budget(db: Database, purpose: str, cat: Catalog | None = None) -> float | None:
    """Cheapest possible build for a purpose (to tell the customer when the budget is too low)."""
    cat = cat or Catalog(await db.all_products())
    best = None
    for cpu in cat.get(CPU):
        for gpu in ([None] if purpose == "office" else [None] + cat.get(GPU)):
            if gpu is None and not cpu.has_igpu:
                continue
            if purpose in ("gaming", "creator") and gpu is None:
                continue
            parts = _complete(cat, purpose, cpu, gpu, Prefs(), budget=0)
            if parts:
                total = sum(p.price for p in parts)
                best = total if best is None else min(best, total)
    return best
