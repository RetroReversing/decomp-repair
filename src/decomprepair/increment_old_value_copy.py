"""A loaded value stored plus a constant and tested afterwards: the old value held in a local of its own, the local advanced in place.

The shape (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`; a 16-instruction N64 function that counts calls in a field and
installs a second callback once the old count passes a bound, 120 -> 0): m2c writes

    t = M2C_FIELD(p, s32 *, 0x8C);
    M2C_FIELD(p, s32 *, 0x8C) = t + 1;
    if (t >= 0xB) { ... }

and the compiler allocates the loaded value and the sum the other way round from the target: the target loads into `$v0`,
copies it (`move $v1,$v0`), increments `$v0` and stores it, and compares the copy (`slti $v1,$v1,0xb`); the single
expression adds into a second register and compares `$v0`. Two things written together make the target's roles: the
copy `u = t;` (the later reads of `t` go to it), and the increment spelled as an assignment to `t` itself, `t = t + 1;`,
stored from `t`. The copy alone, with the store still `t + 1`, stays at 120 (measured), and so does the in-place
increment alone (the compare then reads the sum). The register roles are a hypothesis from the allocator's behaviour
(`u` is the quantity that is live across the compare, `t` is the one that is set again); the judge decides each child.

`variants` finds `lhs = t + K;` (also `t - K`, `K + t`, with the casts to a 32-bit integer and the parentheses m2c writes
around the sum) where `t` is a 32-bit integer local that a statement a few lines above (`t = load;`, in the same
straight-line stretch, with no write to `t` between) set and that is read again after the store. The children:

- `increment_old_value_copy`: `u = t; t = t + K; lhs = t;` at the store, and every later read of `t` reads `u`
  (`TYPE u;` declared beside `t`).
- `increment_old_value_copy_early`: the same, with `u = t;` right after the statement that loaded `t` (offered only when
  that statement is not the one before the store).
- `increment_in_place_store`: a copy `u = t;` that is already there (the later reads use it) and a store still written
  `lhs = t + K;`: the store becomes `t = t + K; lhs = t;`.

Faithful and bounded: `t` is not written after the store, nor has its address taken; no label follows the store (a jump
could arrive without the copy); `lhs` does not mention `t`; the first later read is within a few statements; the type
is 32 bits wide (a narrower `t` would truncate the in-place sum). Nothing else is changed.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, locals_for, view

FAMILY = 'increment_old_value_copy'
EARLY = 'increment_old_value_copy_early'
IN_PLACE = 'increment_in_place_store'
FAMILIES = (FAMILY, EARLY, IN_PLACE)
LIMIT = 8
BEHIND = 4  # statements between the load and the store
AHEAD = 8   # segments between the store and the first later read
WIDE = r'(?:s32|u32|int|unsigned\s+int|unsigned|signed\s+int)'
KEYWORD = re.compile(r'(?:if|else|for|while|do|switch|return|goto|case|default|break|continue)\b')
CAST = re.compile(rf'\(\s*{WIDE}\s*\)\s*')
LABEL = re.compile(rf'(?m)^[ \t]*(?!(?:case|default)\b){IDENT}[ \t]*:(?!:)')


def _python_segments(clean, start, end):
    """[(begin, stop, terminator)] of the text between `;`, `{` and `}` at parenthesis depth 0."""
    found, depth, begin = [], 0, start
    for at in range(start, end):
        char = clean[at]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0 and char in ';{}':
            found.append((begin + len(clean[begin:at]) - len(clean[begin:at].lstrip()), at, char))
            begin = at + 1
    return found


_segments = _python_segments
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _segments(clean, start, end):
        found = _scan.segments(clean, start, end)
        return _python_segments(clean, start, end) if found is NotImplemented else found


def _assignment(text):
    """(left, right) of the first top-level `=` that is an assignment, or None."""
    depth = 0
    for at, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == '=' and depth == 0:
            before, after = text[at - 1:at], text[at + 1:at + 2]
            if after != '=' and before not in '=<>!+-*/%&|^':
                return text[:at].strip(), text[at + 1:].strip()
    return None


def _strip(text):
    """`text` without the casts to a 32-bit integer and the parentheses that wrap all of it."""
    text = text.strip()
    while True:
        cast = CAST.match(text)
        if cast:
            text = text[cast.end():].strip()
        elif text.startswith('(') and _closes_at_end(text):
            text = text[1:-1].strip()
        else:
            return text


def _closes_at_end(text):
    depth = 0
    for at, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if depth == 0:
            return at == len(text) - 1
    return False


def _increment(right, name):
    """(operator, constant) when `right` is `name + K`, `name - K` or `K + name`, else None."""
    right = _strip(right)
    hit = re.fullmatch(rf'{re.escape(name)}\s*([+-])\s*({NUMBER})', right)
    if hit:
        return hit[1], hit[2]
    hit = re.fullmatch(rf'({NUMBER})\s*\+\s*{re.escape(name)}', right)
    return ('+', hit[1]) if hit else None


def _writes(text, name):
    n = re.escape(name)
    return re.search(rf'(?<![\w.]){n}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?<![\w.]){n}\s*(?:\+\+|--)|(?:\+\+|--)\s*{n}\b|(?<!&)&\s*{n}\b', text)


def _indent(clean, at):
    line = clean.rfind('\n', 0, at) + 1
    lead = clean[line:at]
    return lead if not lead.strip() else ' '


def _fresh(source, base):
    name = f'{base}_old'
    number = 1
    while re.search(rf'\b{name}\b', source):
        number += 1
        name = f'{base}_old{number}'
    return name


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    clean = part.clean
    scalars = {decl['name']: decl for decl in locals_for(part) if re.fullmatch(WIDE, decl['type'])}
    if not scalars:
        return []
    segments = _segments(clean, part.opening + 1, part.end - 1)
    results = []
    for index, (begin, stop, mark) in enumerate(segments):
        if mark != ';' or KEYWORD.match(clean[begin:stop].strip() or ';'):
            continue
        text = clean[begin:stop].strip()
        assigned = _assignment(text)
        if not assigned:
            continue
        left, right = assigned
        for var, decl in scalars.items():
            step = _increment(right, var)
            if not step or re.search(rf'\b{var}\b', left):
                continue
            results += _site(source, part, segments, index, begin, stop, left, var, decl, step)
    seen, found = set(), []
    for family, text in results:
        if text != source and text not in seen:
            seen.add(text)
            found.append((family, text))
    return found[:LIMIT]


def _site(source, part, segments, index, begin, stop, left, var, decl, step):
    clean = part.clean
    after = clean[stop + 1:part.end - 1]
    if _writes(after, var) or LABEL.search(after):
        return []
    reads = [hit for hit in re.finditer(rf'(?<![\w.])(?<!->){re.escape(var)}\b(?!\s*:)', clean[stop + 1:part.end - 1])]
    sign, constant = step
    # The statements above the store, back to the one that set `var` (all in one straight-line stretch).
    loaded = None
    for back in range(index - 1, max(index - BEHIND, 0) - 1, -1):
        start, end, mark = segments[back]
        text = clean[start:end].strip()
        if mark != ';':
            break
        if KEYWORD.match(text):
            if _writes(text, var):
                break
            continue
        assigned = _assignment(text)
        if assigned and assigned[0] == var:
            if not re.search(rf'(?<![\w.]){re.escape(var)}\b', assigned[1]):
                loaded = back
            break
        if _writes(text, var):
            break
    out = []
    indent = _indent(clean, begin)
    increment = f'{var} = {var} {sign} {constant};'
    if reads:
        if loaded is None or not _near(clean, segments, index, stop, reads):
            return []
        old = _fresh(source, var)
        declare = (decl.end(), decl.end(), f'\n{_indent(clean, decl.start())}{decl["type"]} {old};')
        flips = [(stop + 1 + hit.start(), stop + 1 + hit.end(), old) for hit in reads]
        copy = f'{old} = {var};'
        store = f'{left} = {var};'
        out.append((FAMILY, edit(source, [declare, (begin, stop + 1, f'{copy}\n{indent}{increment}\n{indent}{store}'), *flips])))
        if loaded != index - 1:
            at = segments[loaded][1] + 1
            out.append((EARLY, edit(source, [declare, (at, at, f'\n{indent}{copy}'), (begin, stop + 1, f'{increment}\n{indent}{store}'), *flips])))
    elif loaded is not None:
        for back in range(loaded + 1, index):
            start, end, mark = segments[back]
            copy = re.fullmatch(rf'({IDENT})\s*=\s*{re.escape(var)}', clean[start:end].strip())
            if copy and re.search(rf'(?<![\w.]){re.escape(copy[1])}\b', clean[stop + 1:part.end - 1]):
                out.append((IN_PLACE, edit(source, [(begin, stop + 1, f'{increment}\n{indent}{left} = {var};')])))
                break
    return out


def _near(clean, segments, index, stop, reads):
    """Whether the first later read of the variable is within AHEAD segments of the store."""
    first = stop + 1 + reads[0].start()
    count = sum(1 for _, end, _ in segments[index + 1:] if end < first)
    return count <= AHEAD


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
