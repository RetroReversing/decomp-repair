"""Literals the target computes from one saved register, written as `base + k` off a variable again.

The target holds a constant in a saved register and makes the others from it (`addiu $s6, $zero, 0x5C` at entry, then
`addiu $a1, $s6, 0x28`, `addiu $a1, $s6, 0x80`; later `addiu $s6, $zero, -0x5A` and `addiu $v0, $s6, 0x96`). That is a
variable the game wrote (a screen's x position, `x`, `x + 0x28`, `x + 0x80`), set again for another layout. m2c
propagates the constant and prints the sums (`0x84`, `0xDC`, `(f32) 0x3C`), so the compiler loads each one on its own and
every saved register after it moves. On a 261-instruction N64 score table (SN GCC 2.8.1, `-G0 -mips3 -O2`) the source
with the variable was 0 and the same source with the sums written out 4806.

The registers come from the target's assembly: a saved register written only by constant loads (and restored from the
stack), and read by `addiu $rd, $reg, k`. A literal in the C that is a call argument, the operand of a floating cast or
the whole right side of a store is one of `K + k` for the constants `K` loaded into that register. Children:

- `register_constant_base`: one variable for the register. The constant loaded first is assigned at the function's
  start; each later constant is assigned before the loop (or statement) that first uses it, in the block that holds all
  of its uses.
- `register_constant_base_per_value`: one variable for each constant instead.

Each is offered with the assignments at a few places (the function's start or after its first constant set; before
the loop, at the block's head or beside the block's last constant set), since the order of the `li`s is the source's.

Offered only where a later assignment cannot reach an earlier constant's use: the block that assigns it ends in a
`return`, is an arm whose `else` holds the remaining uses, or nothing uses the first constant after it. The exact judge
decides every child.
"""
import re

from .c_scan import LOOP_HEADER, header_before
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'register_constant_base'
PER_VALUE = 'register_constant_base_per_value'
FAMILIES = (FAMILY, PER_VALUE)
# (where the first constant is assigned, where the later ones are)
_CHOICES = ((0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2))

_SAVED = r'\$(?:s[0-8]|fp)'
_NUM = r'-?(?:0[xX][0-9a-fA-F]+|\d+)'
_LITERAL = re.compile(r'(?<![\w.])(-?)(0[xX][0-9a-fA-F]+|\d+)(?![\w.])')
_CAST = re.compile(r'\(\s*(?:f32|f64|float|double)\s*\)\s*\Z')
_NOT_CALL = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}
_PUNCTUATION = re.compile(r'[{}();]')


def register_constants(asm):
    """[(register, [constants in the order loaded], {offsets added to it})] for the saved registers that hold constants."""
    loads, offsets, dirty = {}, {}, set()
    for raw in (asm or '').splitlines():
        line = re.sub(r'/\*.*?\*/', '', raw).strip()
        words = line.split(None, 1)
        if len(words) != 2:
            continue
        op, rest = words
        args = [a.strip() for a in rest.split(',')]
        if len(args) == 3 and op in ('addiu', 'ori', 'daddiu') and args[1] == '$zero' and re.fullmatch(_NUM, args[2]):
            if re.fullmatch(_SAVED, args[0]):
                loads.setdefault(args[0], []).append(int(args[2], 0))
            continue
        if len(args) == 2 and op == 'li' and re.fullmatch(_SAVED, args[0]) and re.fullmatch(_NUM, args[1]):
            loads.setdefault(args[0], []).append(int(args[1], 0))
            continue
        if len(args) == 3 and op == 'addiu' and re.fullmatch(_SAVED, args[1]) and re.fullmatch(_NUM, args[2]) \
                and args[0] != args[1]:
            offsets.setdefault(args[1], set()).add(int(args[2], 0))
        # stores and branches read their first operand; a restore from the stack is the epilogue's
        if re.fullmatch(_SAVED, args[0]) and not re.match(r'(?:s[bhwd]|sdc1|b|j|mt)', op) \
                and not (op in ('lw', 'ld') and args[-1].endswith('($sp)')):
            dirty.add(args[0])
    return [(reg, values, offsets[reg]) for reg, values in loads.items() if reg in offsets and reg not in dirty]


def _blocks(clean, opening, end):
    """[(open, close past the brace)] of every brace block of the function body, its own included."""
    stack, out = [], []
    for hit in re.compile(r'[{}]').finditer(clean, opening, end):
        if hit[0] == '{':
            stack.append(hit.start())
        elif stack:
            out.append((stack.pop(), hit.start() + 1))
    return out


def _call_argument(clean, start, stop):
    before = clean[:start].rstrip()
    after = clean[stop:].lstrip()
    if before[-1:] not in ('(', ',') or after[:1] not in (')', ','):
        return False
    depth = 0
    for hit in reversed(list(_PUNCTUATION.finditer(before, max(0, len(before) - 400)))):
        if hit[0] == ')':
            depth += 1
        elif hit[0] != '(':
            return False
        elif depth:
            depth -= 1
        else:
            callee = re.search(rf'({IDENT})\s*\Z', before[:hit.start()])
            return bool(callee) and callee[1] not in _NOT_CALL
    return False


def _used_as_value(clean, start, stop):
    """Whether the literal at [start, stop) stands where a register would be read: argument, float cast or stored value."""
    if _call_argument(clean, start, stop):
        return True
    before = clean[:start].rstrip()
    ends = clean[stop:].lstrip()[:1] == ';'
    if ends and _CAST.search(before):
        return True
    if ends and re.search(r'(?<![=!<>+\-*/&|^%])=\Z', before):
        statement = before[max(before.rfind(';'), before.rfind('{'), before.rfind('}')) + 1:-1]
        return bool(re.search(r'[.\[]|->|^\s*\*|\b[A-Z]?D_[0-9A-Fa-f]{6,}|\bsp[0-9A-F]+\b', statement.strip()))
    return False


def _plan(part, values, offsets):
    """{constant: [(start, stop, offset)]} of the literals that are sums off the register, else None."""
    clean = part.clean
    constants = list(dict.fromkeys(values))
    found = {k: [] for k in constants}
    exact = []
    for hit in _LITERAL.finditer(clean, part.opening + 1, part.end):
        start, stop = hit.start(), hit.end()
        if hit[1]:  # a minus sign, not a subtraction
            if clean[:start].rstrip()[-1:] not in ('(', ',', '=', ')'):
                continue
        if not _used_as_value(clean, start, stop):
            continue
        value = int(hit[2], 0) * (-1 if hit[1] else 1)
        sums = [(abs(value - k), k) for k in constants if value - k in offsets]
        if sums:
            k = min(sums)[1]
            found[k].append((start, stop, value - k))
        elif value in found:
            exact.append((value, (start, stop, 0)))
    found = {k: uses for k, uses in found.items() if uses}
    for value, use in exact:
        if value in found:
            found[value].append(use)
    return {k: sorted(uses) for k, uses in found.items()} or None


def _statements(clean, block):
    """Starts of the direct child statements of a block."""
    ends, depth = [block[0] + 1], 0
    for hit in _PUNCTUATION.finditer(clean, block[0] + 1, block[1] - 1):
        mark = hit[0]
        if mark in '{(':
            depth += 1
            continue
        if mark in '})':
            depth -= 1
        if mark in '};' and depth == 0 and not re.compile(r'\s*(?:else\b|while\b)').match(clean, hit.end()):
            ends.append(hit.end())
    starts = [at + len(clean[at:block[1] - 1]) - len(clean[at:block[1] - 1].lstrip()) for at in ends]
    return [at for at in starts if at < block[1] - 1]


def _statement_start(clean, block, at):
    """Start of the direct child statement of `block` that holds position `at`."""
    return max(start for start in _statements(clean, block) if start <= at)


def _is_loop_body(clean, opening):
    return bool(LOOP_HEADER.search(header_before(clean, opening)))


def _home(clean, blocks, body, uses, others):
    """The block that gets a later constant's assignment: holds all its uses, is no loop body, no other constant's."""
    holding = sorted((b for b in blocks if all(b[0] < s < b[1] for s, _, _ in uses)), key=lambda b: b[1] - b[0])
    for block in holding:
        if any(block[0] < s < block[1] for s, _, _ in others):
            return None
        if _is_loop_body(clean, block[0]):
            continue
        if any(b[0] < block[0] and block[1] <= b[1] and _is_loop_body(clean, b[0]) for b in blocks):
            return None
        # as far out as the block that holds no other constant's use and is not the function's own
        parent = min((b for b in blocks if b[0] < block[0] and block[1] <= b[1]), key=lambda b: b[1] - b[0], default=None)
        return block if parent else (block if block != body else None)
    return None


def _safe(clean, block, first_uses):
    """Whether an assignment inside `block` cannot reach a later read of the first constant."""
    later = [s for s, _, _ in first_uses if s > block[0]]
    if not later:
        return True
    inside = clean[block[0] + 1:block[1] - 1].rstrip()
    if re.search(r'\breturn\b[^;{}]*;\Z', inside):
        return True
    other = re.compile(r'\s*else\s*\{').match(clean, block[1])
    if other:
        end = close(clean, other.end() - 1, '{', '}')
        return bool(end) and all(s < end for s in later)
    return False


def _line_insert(source, at, text):
    line = source.rfind('\n', 0, at) + 1
    indent = source[line:at]
    if indent.strip():
        return (at, at, f'{text} ')
    return (line, line, f'{indent}{text}\n')


def _sum(name, offset):
    if not offset:
        return name
    return f'({name} + {hex(offset)})' if offset > 0 else f'({name} - {hex(-offset)})'


def _first_statement(clean, body):
    """Where the function's declarations end."""
    at = body[0] + 1
    declaration = re.compile(r'\s*(?!return\b|goto\b|else\b)(?:[A-Za-z_]\w*[\s*]+)+[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?'
                             r'(?:=[^;{}]*)?;')
    while True:
        hit = declaration.match(clean, at)
        if not hit:
            return at + len(clean[at:]) - len(clean[at:].lstrip())
        at = hit.end()


_CONSTANT_SET = re.compile(rf'[A-Za-z_]\w*\s*=\s*{_NUM}\s*;')


def _children(clean, block):
    """Starts of the direct child statements of a block, past its declarations."""
    first = _first_statement(clean, block)
    return [at for at in _statements(clean, block) if at >= first]


def _places(clean, block, use, first):
    """Where the assignment can go: the default, then the block's head or beside its neighbouring constant sets."""
    starts = _children(clean, block)
    sets = [at for at in starts if _CONSTANT_SET.match(clean, at)]
    if first:
        places = [starts[0] if starts else _first_statement(clean, block)]
        if sets:  # after the first constant set (a loop counter's start), before the others
            index = starts.index(sets[0])
            if index + 1 < len(starts):
                places.append(starts[index + 1])
    else:
        loop = _statement_start(clean, block, use)
        places = [loop, _first_statement(clean, block)]
        earlier = [at for at in sets if at < loop]
        if earlier:
            places.append(earlier[-1])
    return list(dict.fromkeys(places))


def _build(source, part, plan, first, per_value, serial, choice):
    clean = part.clean
    blocks = _blocks(clean, part.opening, part.end)
    body = next(b for b in blocks if b[0] == part.opening)
    order = ([first] if first in plan else []) + [k for k in plan if k != first]
    names = {}
    for index, k in enumerate(order):
        stem = f'reg_base{serial}' if not per_value else f'reg_base{serial}_{index}'
        if re.search(rf'\b{stem}\b', clean):
            return None
        names[k] = stem
    edits = [(s, e, _sum(names[k], off)) for k, uses in plan.items() for s, e, off in uses]
    declared = list(dict.fromkeys(names[k] for k in order))
    opening_lines = [f's32 {name};' for name in declared]
    head = ''.join(f'\n    {line}' for line in opening_lines)
    edits.append((part.opening + 1, part.opening + 1, head))
    places = _places(clean, body, None, True)
    if choice[0] >= len(places):
        return None
    inserts = {places[choice[0]]: [f'{names[order[0]]} = {order[0]:#x};']}
    for k in order[1:]:
        others = [u for j, uses in plan.items() if j != k for u in uses]
        block = _home(clean, blocks, body, plan[k], others)
        if not block or block == body or not _safe(clean, block, plan[order[0]] if not per_value else []):
            return None
        places = _places(clean, block, plan[k][0][0], False)
        inserts.setdefault(places[min(choice[1], len(places) - 1)], []).append(f'{names[k]} = {k:#x};')
    for at, lines in inserts.items():
        line = source.rfind('\n', 0, at) + 1
        indent = source[line:at] if not source[line:at].strip() else ' '
        edits.append(_line_insert(source, at, f'\n{indent}'.join(lines)))
    return edit(source, edits)


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    out = []
    for serial, (_, values, offsets) in enumerate(register_constants(asm)[:3]):
        plan = _plan(part, values, offsets)
        if not plan:
            continue
        first = values[0] if values[0] in plan else next(iter(plan))
        for family, per_value in ((FAMILY, False), (PER_VALUE, True)):
            if per_value and len(plan) < 2:
                continue
            for choice in _CHOICES:
                child = _build(source, part, plan, first, per_value, serial or '', choice)
                if child and child != source and (family, child) not in out:
                    out.append((family, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
