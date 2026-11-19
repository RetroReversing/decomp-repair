"""Read-only pointers written `const`, so the compiler may move their loads into the prologue.

gcc 2.7.2 (KMC, N64) treats a load from memory it knows is read-only as unable to conflict with the stack stores of
the prologue, so its scheduler lifts such loads up between the register saves, sometimes above the stack-pointer
adjustment. Through a plain pointer the same loads stay below every save. Three N64 functions whose target loads
through an argument register before its last save were 580, 615 and 1275 points off with m2c's C, and exact once
the pointers they only read were `const` (a `const f32 *` parameter, or `M2C_FIELD(x, const f32 *, off)` reads with
the writes left plain). Earlier passes took them for another compiler's code.

Three variants: the reads and the parameters only read made `const`; the reads alone; the parameters alone. They
change no behaviour. `early_load(asm)` says whether the target shows the habit (an argument-based load before the
last save), which callers use to try these first.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'const_read'
FAMILIES = (FAMILY,)

SAVE = re.compile(r'^(?:\s*/\*.*?\*/)?\s*(?:sw|sd|swc1|sdc1)\s+\$\w+\s*,\s*-?(?:0x[0-9a-fA-F]+|\d+)\(\$sp\)', re.M)
ARG_LOAD = re.compile(r'^(?:\s*/\*.*?\*/)?\s*(?:lw|ld|lh|lhu|lb|lbu|lwc1|ldc1)\s+\$\w+\s*,\s*-?(?:0x[0-9a-fA-F]+|\d+)\(\$a[0-3]\)', re.M)
FIELD = re.compile(r'M2C_FIELD\(\s*(\w+)\s*,\s*((?!const\b)[\w ]+?\*)\s*,')
PARAM = re.compile(r'^\s*((?!const\b)[A-Za-z_][\w ]*?)\s*\*\s*(\w+)\s*$')


def early_load(asm):
    """True when the target loads through an argument register before its last register save."""
    asm = asm or ''
    # (the prologue only: a spill after the first call or branch isn't a save the loads were lifted between)
    stop = re.search(r'^(?:\s*/\*.*?\*/)?\s*(?:jal|jalr|jr|j|b\w*)\s', asm, re.M)
    asm = asm[:stop.start()] if stop else asm
    saves = [m.start() for m in SAVE.finditer(asm)]
    if not saves:
        return False
    return any(m.start() < saves[-1] for m in ARG_LOAD.finditer(asm))


def _written(body, var):
    """Whether `var`'s memory is written, passed on, or stepped (so making it const could break or change the C)."""
    v = re.escape(var)
    if re.search(rf'M2C_FIELD\(\s*{v}\s*,[^;]*?\)\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', body):
        return True
    if re.search(rf'(?:\*\s*\(?\s*{v}\b[^;=]*|\b{v}\s*\[[^\]]*\]\s*)(?:[-+*/|&^]|<<|>>)?=(?!=)', body):
        return True
    if re.search(rf'\b{v}\s*->', body) or re.search(rf'(?:\+\+|--)\s*{v}\b|\b{v}\s*(?:\+\+|--)|\b{v}\s*[-+]?=(?!=)', body):
        return True
    # passed bare to a call: the callee may write through it, or need it non-const
    calls = re.sub(r'M2C_FIELD\(', '(', body)  # (m2c's field macro is a read, not a call)
    return bool(re.search(rf'\w\s*\([^;()]*?(?<![\w.]){v}(?![\w\[])\s*[,)]', calls))


def _reads(body):
    """M2C_FIELD reads made const: every M2C_FIELD that isn't the target of an assignment."""
    out, last = [], 0
    for m in FIELD.finditer(body):
        depth, i = 0, m.start() + len('M2C_FIELD')
        while i < len(body):
            depth += body[i] == '('
            depth -= body[i] == ')'
            if depth == 0:
                break
            i += 1
        if re.match(r'\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', body[i + 1:]):
            continue
        out.append(body[last:m.start(2)] + 'const ' + m[2])
        last = m.end(2)
    return ''.join(out) + body[last:] if out else body


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    paren = clean.find('(', span[0], span[1])
    opening = clean.find('{', span[0], span[1])
    if paren < 0 or opening < 0 or (end := close(clean, opening, '{', '}')) is None:
        return []
    shut = close(clean, paren, '(', ')')  # (close gives the index just past the bracket)
    if shut is None or shut > opening:
        return []
    shut -= 1
    params, body = source[paren + 1:shut], source[opening:end]
    pieces = params.split(',')
    made = list(pieces)
    for k, piece in enumerate(pieces):
        hit = PARAM.match(piece)
        if hit and not _written(body, hit[2]):
            made[k] = piece[:hit.start(1)] + 'const ' + piece[hit.start(1):]
    new_params = ','.join(made) if made != pieces else None
    new_body = _reads(body)
    new_body = new_body if new_body != body else None

    def build(p, b):
        return source[:paren + 1] + (p or params) + source[shut:opening] + (b or body) + source[end:]
    found = []
    for p, b in ((new_params, new_body), (None, new_body), (new_params, None)):
        if p is None and b is None:
            continue
        text = build(p, b)
        if text != source and text not in found:
            found.append(text)
    return [(FAMILY, text) for text in found]
