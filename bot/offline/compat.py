"""Rule-based compatibility checks between PC parts."""

from dataclasses import dataclass

from ..db import Product
from .specs import CASE, COOLING, CPU, GPU, MB, PSU, RAM, Part


@dataclass
class Issue:
    level: str  # "error" (won't work) | "warn" (works, but think twice)
    text: str

    def __str__(self) -> str:
        return ("❌ " if self.level == "error" else "⚠️ ") + self.text


def _by_cat(parts: list[Part]) -> dict[str, list[Part]]:
    out: dict[str, list[Part]] = {}
    for p in parts:
        out.setdefault(p.category, []).append(p)
    return out


def psu_needed(cpu: Part | None, gpu: Part | None) -> float:
    """Minimum sensible PSU wattage."""
    if gpu and gpu.recommended_psu:
        base = gpu.recommended_psu
    else:
        base = 300 + (150 if gpu else 0)
    cpu_extra = max((cpu.tdp or 65) - 65, 0) * 1.2 if cpu else 0
    return base + cpu_extra


def check(products: list[Product], full_build: bool | None = None) -> list[Issue]:
    """full_build: also report missing pieces (cooler, graphics). Defaults to True for 4+ kinds of parts."""
    parts = [Part(p) for p in products]
    cat = _by_cat(parts)
    issues: list[Issue] = []
    cpus, mbs, rams, gpus = cat.get(CPU, []), cat.get(MB, []), cat.get(RAM, []), cat.get(GPU, [])
    psus, cases = cat.get(PSU, []), cat.get(CASE, [])
    coolers = [c for c in cat.get(COOLING, []) if c.cooler_kind != "paste"]

    for label, group in (("процессора", cpus), ("материнские платы", mbs), ("блока питания", psus),
                         ("корпуса", cases)):
        if len(group) > 1:
            issues.append(Issue("warn", f"Выбрано несколько: {label} ({len(group)} шт.) — для одной сборки нужен один."))

    for cpu in cpus:
        for mb in mbs:
            if cpu.socket and mb.socket and cpu.socket != mb.socket:
                issues.append(Issue("error", f"{cpu.name} (сокет {cpu.socket}) не встанет в {mb.name} "
                                             f"(сокет {mb.socket})."))
            elif cpu.memory_types and mb.memory_types and not cpu.memory_types & mb.memory_types:
                issues.append(Issue("error", f"{cpu.name} и {mb.name} поддерживают разные типы памяти."))

    for ram in rams:
        for mb in mbs:
            if ram.ram_type and mb.memory_types and ram.ram_type not in mb.memory_types:
                issues.append(Issue("error", f"Память {ram.ram_type} ({ram.name}) не подходит к {mb.name} — "
                                             f"плата поддерживает {'/'.join(sorted(mb.memory_types))}."))
        if not mbs:
            for cpu in cpus:
                if ram.ram_type and cpu.memory_types and ram.ram_type not in cpu.memory_types:
                    issues.append(Issue("error", f"{cpu.name} не работает с памятью {ram.ram_type}."))

    for case in cases:
        for mb in mbs:
            if mb.form_factor and case.case_boards and mb.form_factor not in case.case_boards:
                issues.append(Issue("error", f"Плата формата {mb.form_factor} не поместится в {case.name} "
                                             f"(поддерживает {', '.join(sorted(case.case_boards))})."))
        for gpu in gpus:
            if gpu.length_mm and case.max_gpu_mm and gpu.length_mm > case.max_gpu_mm:
                issues.append(Issue("error", f"{gpu.name} длиной {gpu.length_mm:.0f} мм не влезет в {case.name} "
                                             f"(макс. {case.max_gpu_mm:.0f} мм)."))
        for cooler in coolers:
            if cooler.cooler_kind == "air" and cooler.cooler_height and case.max_cooler_mm \
                    and cooler.cooler_height > case.max_cooler_mm:
                issues.append(Issue("error", f"Кулер {cooler.name} ({cooler.cooler_height:.0f} мм) выше, чем "
                                             f"позволяет {case.name} (макс. {case.max_cooler_mm:.0f} мм)."))
            if cooler.cooler_kind == "aio" and cooler.radiator_mm and case.max_radiator_mm \
                    and cooler.radiator_mm > case.max_radiator_mm:
                issues.append(Issue("error", f"Радиатор {cooler.radiator_mm:.0f} мм не поместится в {case.name} "
                                             f"(макс. {case.max_radiator_mm:.0f} мм)."))
        for psu in psus:
            if case.case_psu == "SFX" and psu.psu_form_factor != "SFX":
                issues.append(Issue("error", f"{case.name} рассчитан на блок питания SFX, а {psu.name} — "
                                             f"{psu.psu_form_factor}."))

    for cooler in coolers:
        for cpu in cpus:
            if cpu.socket and cooler.cooler_sockets and cpu.socket not in cooler.cooler_sockets:
                issues.append(Issue("error", f"Кулер {cooler.name} не поддерживает сокет {cpu.socket}."))
            elif cpu.tdp and cooler.tdp and cooler.tdp < cpu.tdp:
                issues.append(Issue("warn", f"Кулер {cooler.name} (до {cooler.tdp:.0f} Вт) слабоват для "
                                            f"{cpu.name} ({cpu.tdp:.0f} Вт)."))

    for psu in psus:
        need = psu_needed(cpus[0] if cpus else None, gpus[0] if gpus else None)
        if psu.watts and (gpus or cpus) and psu.watts < need:
            what = gpus[0].name if gpus else cpus[0].name
            level = "error" if gpus and gpus[0].recommended_psu and psu.watts < gpus[0].recommended_psu else "warn"
            issues.append(Issue(level, f"Блока питания {psu.watts:.0f} Вт мало для {what}: "
                                       f"рекомендуется от {need:.0f} Вт."))

    # Missing pieces, only for a full build.
    if full_build is None:
        full_build = len(cat) >= 4
    if full_build and cpus and mbs:
        cpu = cpus[0]
        if not cpu.boxed_cooler and not coolers:
            issues.append(Issue("warn", f"У {cpu.name} нет кулера в комплекте — добавьте кулер."))
        if not gpus and not cpu.has_igpu:
            issues.append(Issue("warn", f"У {cpu.name} нет встроенной графики — нужна видеокарта."))
    return issues


def compatible_boards(cpu: Part, boards: list[Part]) -> list[Part]:
    return [mb for mb in boards if mb.socket == cpu.socket
            and (not cpu.memory_types or not mb.memory_types or cpu.memory_types & mb.memory_types)]


def compatible_cpus(board: Part, cpus: list[Part]) -> list[Part]:
    return [cpu for cpu in cpus if cpu.socket == board.socket
            and (not cpu.memory_types or not board.memory_types or cpu.memory_types & board.memory_types)]


def compatible_ram(board: Part, rams: list[Part]) -> list[Part]:
    return [r for r in rams if not board.memory_types or r.ram_type in board.memory_types]


def fits_case(case: Part, board: Part | None = None, gpu: Part | None = None, cooler: Part | None = None) -> bool:
    if board and board.form_factor and case.case_boards and board.form_factor not in case.case_boards:
        return False
    if gpu and gpu.length_mm and case.max_gpu_mm and gpu.length_mm > case.max_gpu_mm:
        return False
    if cooler and cooler.cooler_kind == "air" and cooler.cooler_height and case.max_cooler_mm \
            and cooler.cooler_height > case.max_cooler_mm:
        return False
    if cooler and cooler.cooler_kind == "aio" and cooler.radiator_mm and case.max_radiator_mm \
            and cooler.radiator_mm > case.max_radiator_mm:
        return False
    return True


def cooler_fits_cpu(cooler: Part, cpu: Part) -> bool:
    if cooler.cooler_kind == "paste":
        return False
    if cpu.socket and cooler.cooler_sockets and cpu.socket not in cooler.cooler_sockets:
        return False
    return not (cpu.tdp and cooler.tdp and cooler.tdp < cpu.tdp)


def confirmations(products: list[Product]) -> list[str]:
    """Human-readable list of what was checked and is fine (shown under builds and compatibility answers)."""
    parts = [Part(p) for p in products]
    cat = _by_cat(parts)
    cpu = (cat.get(CPU) or [None])[0]
    mb = (cat.get(MB) or [None])[0]
    ram = (cat.get(RAM) or [None])[0]
    gpu = (cat.get(GPU) or [None])[0]
    psu = (cat.get(PSU) or [None])[0]
    case = (cat.get(CASE) or [None])[0]
    cooler = next((c for c in cat.get(COOLING, []) if c.cooler_kind != "paste"), None)
    ok = []
    if cpu and mb and cpu.socket == mb.socket:
        ok.append(f"сокет {cpu.socket} — процессор и плата совпадают")
    if ram and mb and ram.ram_type in mb.memory_types:
        ok.append(f"память {ram.ram_type} поддерживается платой")
    if case and mb and mb.form_factor in case.case_boards:
        ok.append(f"плата {mb.form_factor} помещается в корпус")
    if gpu and case and gpu.length_mm and case.max_gpu_mm and gpu.length_mm <= case.max_gpu_mm:
        ok.append(f"видеокарта {gpu.length_mm:.0f} мм ≤ {case.max_gpu_mm:.0f} мм в корпусе")
    if psu and psu.watts:
        need = psu_needed(cpu, gpu)
        if psu.watts >= need:
            ok.append(f"блок питания {psu.watts:.0f} Вт ≥ нужных ~{need:.0f} Вт")
    if cooler and cpu and cpu.socket in cooler.cooler_sockets:
        ok.append(f"кулер поддерживает {cpu.socket}" + (f" и {cpu.tdp:.0f} Вт TDP" if cpu.tdp else ""))
    elif cpu and cpu.boxed_cooler and not cooler:
        ok.append("кулер идёт в комплекте с процессором")
    return ok
