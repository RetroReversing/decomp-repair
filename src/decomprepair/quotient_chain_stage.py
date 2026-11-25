"""A quotient divided again after a shift, staged through a local so the compiler cannot fold the two divisions.

m2c writes a fixed-point count as one expression, `(((x * n) / 1000) >> 6) / 3`. KMC gcc 2.7.2 folds that into a single
division by `64000 * 3` (one multiply by a constant, one shift) where the target divides by 1000 first, keeps the
quotient, then divides it by 3 and shifts: `multu` by 0x10624DD3, `srl 6`, `multu` by 0xAAAAAAAB, `srl 7`. The
shift moves after the second division (equal for unsigned values) and the first quotient goes into a local of its own,
which (hypothesis, not read in the compiler source) keeps the front end from merging `(a / 1000) / 3` into one division. 575 -> 280 on a 157-instruction sound-engine setup function
(its allocation and loop shapes then took two more steps, `loop_index_inline_guard` and `reused_counter_split_scope`).

Only for unsigned operands: the dividend names a `(u32)` cast, an unsigned literal, or a variable declared `u32` (the
usual conversions make a product with one unsigned word unsigned).
That a fold is what the target avoids is a hypothesis read from the constants in the target's assembly, which the
family checks first (both magic multiplies for the two divisors) when it is given the assembly.
"""
import re

from .csource import _blank, find

FAMILY = 'quotient_chain_stage'
FAMILIES = (FAMILY,)
ID = r'[A-Za-z_]\w*'
_TAIL = re.compile(r'>>\s*(?P<shift>\d{1,2})\s*\)\s*/\s*(?P<divisor>\d+)(?P<suffix>[uU]?)(?![\w.])')
_MAGIC = {1000: '0x10624dd3', 3: '0xaaaaaaab', 5: '0xcccccccd', 10: '0xcccccccd', 7: '0x24924925'}
_UNSIGNED = re.compile(r'\b(?:u32|u16|u8|uint32_t|uint16_t|uint8_t|unsigned(?:\s+(?:int|short|char))?)\b')


def _python_open(text, close):
    """The index of the `(` that matches the `)` at `close`, or None."""
    depth = 0
    for i in range(close, -1, -1):
        if text[i] == ')':
            depth += 1
        elif text[i] == '(':
            depth -= 1
            if not depth:
                return i
    return None


_open = _python_open
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _open(text, close):
        found = _scan.open_if(text, close, '(', ')', None)
        return _python_open(text, close) if found is NotImplemented else found


def _top_division(inner):
    """(dividend, divisor, suffix) of `inner` when it is `E / <integer>` at its own level (outer parentheses removed)."""
    inner = inner.strip()
    while inner.startswith('(') and inner.endswith(')') and _open(inner, len(inner) - 1) == 0:
        inner = inner[1:-1].strip()
    depth = 0
    for i in range(len(inner) - 1, -1, -1):
        ch = inner[i]
        depth += ch == ')'
        depth -= ch == '('
        if ch == '/' and not depth:
            tail = re.fullmatch(r'(\d+)([uU]?)', inner[i + 1:].strip())
            if tail and inner[i - 1:i] not in '/*' and inner[i + 1:i + 2] not in '/*':
                return inner[:i].strip(), int(tail[1]), tail[2]
            return None
    return None


def _unsigned(dividend, clean):
    """Word-width unsigned: a `(u32)` cast, a `u` literal, or a variable declared `u32` (narrower types promote to int)."""
    if re.search(r'\(\s*(?:u32|unsigned(?:\s+int)?|uint32_t)\s*\)', dividend) or re.search(r'\b\d+[uU]\b', dividend):
        return True
    word = r'(?:u32|uint32_t|unsigned(?:\s+int)?)'
    return any(re.search(rf'\b{word}\s+(?:\*\s*)*(?:[\w\s,*]*,\s*)?{n}\b', clean)
               for n in set(re.findall(ID, dividend)) - {'sizeof'})


def _magic_ok(asm, first, second):
    if not asm:
        return True
    text = asm.lower()
    return all(_MAGIC.get(d, '') in text for d in (first, second) if d in _MAGIC)


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    quotient = '__repair_quotient'
    while quotient in set(re.findall(ID, clean)):
        quotient += '_'
    for hit in _TAIL.finditer(clean, *span):
        group = _open(clean, hit.start() + hit.group().index(')'))
        if group is None or group < span[0]:
            continue
        division = _top_division(clean[group + 1:hit.start()])
        if not division:
            continue
        dividend, first, _ = division
        second = int(hit['divisor'])
        if first < 2 or second < 2 or not _unsigned(dividend, clean[span[0]:span[1]]) or not _magic_ok(asm, first, second):
            continue
        start = max(clean.rfind(c, span[0], group) for c in ';{}') + 1
        head = clean[start:group]
        # a statement of its own: `name = ((`, not a condition, a loop header or a call's arguments
        if not re.fullmatch(r'\s*[\w.\[\]>*\-]+\s*=\s*\(*\s*', head):
            continue
        indent = re.match(r'\s*', source[start:group]).group().split('\n')[-1]
        replacement = f'(({quotient} / {second}{hit["suffix"]}) >> {hit["shift"]})'
        brace = source.index('{', span[0])
        staged = f'\n{indent}{quotient} = {dividend} / {first};'
        new = (source[:brace + 1] + f'\n  u32 {quotient};' + source[brace + 1:start] + staged
               + source[start:group] + replacement + source[hit.end():])
        return [(FAMILY, new)]
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
