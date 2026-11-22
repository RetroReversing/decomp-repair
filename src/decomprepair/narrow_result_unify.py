"""A clamped result kept in one narrow local, and a comparison read with its sides the way the compiler extends them.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) menu function that stood at 125: a byte read from a record,
moved by a signed step, clamped between a halfword and the halfword above it (both packed in one word), then stored,
tested and passed on. m2c wrote it with two locals for the one value, a wide `s32` that carries the result and an `s16`
the compare reads, the wide one copied into the narrow one before the clamp and back after it. Two edits closed it
(125 -> 220 -> 0; each alone scored 220 or no better, so they pay off only together):

narrow_result_unify
    The wide local is only a carrier for the narrow one: its writes are the first load and the clamp's arms, its one
    read before the clamp is `narrow = wide + step;`, and the whole is closed by `narrow = wide;`. Everything goes
    through the narrow local alone (`narrow = load; narrow = narrow + step; if (...) narrow = hi; else if (...) narrow =
    lo;`). The target then has `addu $v0,$s1,$s4; move $s1,$v0` (the narrow pseudo is set by a halfword move that is
    not extended, so the sum keeps its own register) and extends that register at the compares (`sll/sra $v0`), where
    the two-local form extended into the result's register (`sra $s1,$v0,16`), a different allocation. Hypothesis from
    the `-dr` dump, not from the compiler source: a halfword assignment from a word is a `subreg` move without an
    extension, and cse then reads the extension from the sum's register.

compare_sides_locals / compare_sides_inline
    `if (mask < narrow)` written `if (narrow > mask)`. gcc evaluates the left operand first, so the signed halfword's
    `sll/sra` came before the unsigned halfword's `andi` in the target and after it in ours. The first family swaps the
    sides of a comparison of two plain operands (a name, a cast of a name, a name masked with a constant); the second
    does it after writing a single-use mask local (`t = lo & 0xFFFF; if (t < x)`) into the comparison, since a local
    set far above keeps its `andi` far above. The meaning never changes.

narrow_result_unify_compare
    The two together as one child, the form that scored 0.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view
from .pattern_repairs import close

FAMILY_UNIFY = 'narrow_result_unify'
FAMILY_SWAP = 'compare_sides_locals'
FAMILY_INLINE = 'compare_sides_inline'
FAMILY_BOTH = 'narrow_result_unify_compare'
FAMILIES = (FAMILY_UNIFY, FAMILY_SWAP, FAMILY_INLINE, FAMILY_BOTH)
LIMIT = 6
NARROW = {'s8', 'u8', 's16', 'u16', 'char', 'short', 'signed char', 'unsigned char', 'signed short', 'unsigned short'}
WIDE = {'s32', 'u32', 'int', 'unsigned', 'unsigned int', 'signed int'}
FLIP = {'<': '>', '>': '<', '<=': '>=', '>=': '<='}
_DECLARATION = re.compile(rf'\b(?P<type>{INTEGER})\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})*)\s*;')
_WRITE = r'(?:=(?!=)|\+\+|--|[-+*/%&|^]=|<<=|>>=)'
_SIDE = re.compile(rf'(?:\(\s*{INTEGER}\s*\)\s*)?(?:{IDENT}|\(\s*{IDENT}\s*&\s*{NUMBER}\s*\))')


def _norm(type_text):
    return re.sub(r'\s+', ' ', type_text.strip())


def _declared(part):
    """name -> (declaration match, normalised type) for the plain scalar locals declared before any other statement."""
    result = {}
    for hit in _DECLARATION.finditer(part.clean, part.opening + 1, part.end):
        before = part.clean[part.opening + 1:hit.start()].rstrip()
        if before and before[-1] not in ';{}':
            continue
        for name in re.split(r'\s*,\s*', hit['names']):
            result[name] = (hit, _norm(hit['type']))
    return result


def _drop_declaration(source, part, name):
    """The edit that removes `name` from its (possibly comma) declaration, or None."""
    found = _declared(part).get(name)
    if not found:
        return None
    hit = found[0]
    names = [n for n in re.split(r'\s*,\s*', hit['names']) if n != name]
    text = f'{hit["type"]} {", ".join(names)};' if names else ''
    return (hit.start(), hit.end(), text)


def _count(body, name):
    return len(re.findall(rf'\b{re.escape(name)}\b', body))


def _unify(source, name):
    part = view(source, name)
    if not part:
        return []
    body_start, body_end = part.opening + 1, part.end - 1
    clean = part.clean
    declared = _declared(part)
    result = []
    for narrow, (_, narrow_type) in declared.items():
        if narrow_type not in NARROW:
            continue
        for wide, (_, wide_type) in declared.items():
            if wide_type not in WIDE:
                continue
            text = _unify_pair(source, part, narrow, wide, body_start, body_end, clean)
            if text:
                result.append(text)
    return result


def _unify_pair(source, part, narrow, wide, body_start, body_end, clean):
    n, w = re.escape(narrow), re.escape(wide)
    span = clean[body_start:body_end]
    back = list(re.finditer(rf'\b{n}\s*=\s*{w}\s*;', span))
    forward = list(re.finditer(rf'\b{w}\s*=\s*{n}\s*;', span))
    if len(back) != 1 or len(forward) != 1:
        return None
    back, forward = back[0], forward[0]
    if forward.end() > back.start():
        return None
    steps = [m for m in re.finditer(rf'\b{n}\s*=\s*{w}\s*([-+])\s*([^;=]*);', span)]
    if any(re.search(rf'\b{w}\b', m[2]) or re.search(IDENT + r'\s*\(', m[2]) for m in steps):
        return None
    # every write of the narrow local is a step or the copy back, and every read of the wide one is one of them
    narrow_writes = [m for m in re.finditer(rf'\b{n}\s*{_WRITE}', span)]
    allowed = [(m.start(), m.end()) for m in steps] + [(back.start(), back.end())]
    for m in narrow_writes:
        if not any(a <= m.start() < b for a, b in allowed):
            return None
    wide_writes = [m for m in re.finditer(rf'\b{w}\s*{_WRITE}', span)]
    covered = {m.start() for m in wide_writes}
    decl = _declared(part)[wide][0]
    reads = [m for m in re.finditer(rf'\b{w}\b', span) if m.start() not in covered
             and not decl.start() <= body_start + m.start() < decl.end()]
    inside = [(m.start(), m.end()) for m in steps] + [(back.start(), back.end())]
    if any(not any(a <= m.start() < b for a, b in inside) for m in reads):
        return None
    arms = [m for m in wide_writes if forward.end() <= m.start() < back.start()]
    earlier = [m for m in wide_writes if m.start() < forward.start()]
    if len(arms) + len(earlier) + 1 != len(wide_writes) or not arms:
        return None
    # the stretch between the copy and the copy back is one `if` / `else if` chain whose arms only set the wide local
    stretch = span[forward.end():back.start()]
    blanked, at = '', 0
    for head in re.finditer(r'\bif\s*\(', stretch):
        if head.start() < at:
            continue
        end = close(stretch, head.end() - 1)
        if end is None:
            return None
        blanked += stretch[at:head.start()] + ' ' * (end - head.start())
        at = end
    blanked += stretch[at:]
    if not re.fullmatch(rf'(?:\s|\{{|\}}|\belse\b|{IDENT}\s*=(?!=)[^;]*;)*', blanked):
        return None
    for target, value in re.findall(rf'({IDENT})\s*=(?!=)([^;]*);', blanked):
        if target == narrow or re.search(rf'\b{n}\b', value) or (target != wide and re.search(rf'\b{w}\b', value)):
            return None
    for later in span[back.end():].split(';'):
        if re.search(rf'\b{w}\b', later):
            return None
    drop = _drop_declaration(part.source, part, wide)
    if not drop:
        return None
    edits = [drop, (body_start + forward.start(), body_start + forward.end(), ''),
             (body_start + back.start(), body_start + back.end(), '')]
    for m in wide_writes:
        if m.start() != forward.start():
            edits.append((body_start + m.start(), body_start + m.start() + len(wide), narrow))
    for m in steps:
        at = body_start + m.start(0)
        edits.append((at, body_start + m.end(0), re.sub(rf'=\s*{w}\b', f'= {narrow}', part.source[at:body_start + m.end(0)], 1)))
    return edit(source, edits)


def _depth_ok(clean, start, stop):
    depth = 0
    for char in clean[start:stop]:
        depth += (char == '{') - (char == '}')
        if depth < 0:
            return False
    return True


def _inline_side(source, part, side, if_start):
    """`(expr)` for a bare local `side` assigned once from a plain expression before the `if`, and the edits that remove
    its assignment and declaration; or None."""
    if not re.fullmatch(IDENT, side):
        return None
    clean = part.clean
    span = clean[part.opening + 1:part.end - 1]
    if _count(span, side) != 3:
        return None
    assign = re.search(rf'\b{re.escape(side)}\s*=(?!=)\s*([^;]+);', clean[part.opening + 1:if_start])
    if not assign:
        return None
    expr = assign[1].strip()
    if not re.fullmatch(r'[\w\s&|^+\-*()]+', expr) or re.search(rf'(?<![\w)]){IDENT}\s*\(', expr):
        return None
    start = part.opening + 1 + assign.start()
    stop = part.opening + 1 + assign.end()
    if not _depth_ok(clean, stop, if_start):
        return None
    if any(re.search(rf'\b{re.escape(i)}\s*{_WRITE}', clean[stop:if_start]) for i in set(re.findall(IDENT, expr))):
        return None
    drop = _drop_declaration(source, part, side)
    if not drop:
        return None
    return f'({expr})', [(start, stop, ''), drop]


def _compares(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = []
    for head in re.finditer(r'\bif\s*\(', clean[part.opening:part.end]):
        open_at = part.opening + head.end() - 1
        end = close(clean, open_at)
        if end is None:
            continue
        cond_start, cond_end = open_at + 1, end - 1
        cond = clean[cond_start:cond_end]
        depth, ops = 0, []
        for i, char in enumerate(cond):
            depth += (char == '(') - (char == ')')
            if depth:
                continue
            if char in '<>' and not re.match(r'<<|>>|->|<=|>=', cond[i:i + 2]) and cond[i - 1:i + 1] not in ('<<', '>>', '->'):
                ops.append((i, char))
            elif cond[i:i + 2] in ('<=', '>='):
                ops.append((i, cond[i:i + 2]))
            elif cond[i:i + 2] in ('&&', '||', '==', '!=') or char in '?!':
                ops.append((i, 'bad'))
        if len(ops) != 1 or ops[0][1] == 'bad':
            continue
        at, op = ops[0]
        left, right = cond[:at].strip(), cond[at + len(op):].strip()
        if not (_SIDE.fullmatch(left) and _SIDE.fullmatch(right)):
            continue
        found.append((cond_start, cond_end, left, op, right, part.opening + head.start()))
    return found


def _swap_children(source, name):
    result = []
    for cond_start, cond_end, left, op, right, if_start in _compares(source, name):
        part = view(source, name)
        result.append((FAMILY_SWAP, edit(source, [(cond_start, cond_end, f'{right} {FLIP[op]} {left}')])))
        for side, other in ((left, right), (right, left)):
            inline = _inline_side(source, part, side, if_start)
            if inline:
                text, edits = inline
                # swapped: the other side now comes first, and the inlined mask stands on the right
                new = f'{other} {FLIP[op]} {text}' if side == left else f'{text} {FLIP[op]} {other}'
                result.append((FAMILY_INLINE, edit(source, edits + [(cond_start, cond_end, new)])))
    return result


def variants(source, name):
    result = [(FAMILY_UNIFY, text) for text in _unify(source, name)]
    for _, merged in list(result):
        for family, text in _swap_children(merged, name):
            if family == FAMILY_INLINE:
                result.append((FAMILY_BOTH, text))
    result.extend(_swap_children(source, name))
    return result[:LIMIT * 2]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
