"""A local initialised before a label that a `goto` from outside the block enters past it, set at the label instead.

m2c (and the agents' earlier edits) write `{ u8 *base = &table; s32 dst; ...; L: dst = idx * 0x86; ... }` for a block
two paths enter: the fall-through path runs the initialiser, but the `goto L` path jumps past it and reads an
unset pointer. The compiler reads the C as written, so the branch lands one instruction late (after the address
load) and a register or delay slot differs; the game's source set the value where both paths meet. A table-copy
function of a sound-bank cache (KMC GCC 2.7.2, `-O2`) went 30 -> 70 with the initialiser moved after the label
(a faithful program again, the `lui`/`addiu` pair now sits at the branch target, in the register the target has),
and 70 -> 0 once a byte index was also widened into an `int` before the address load.

Why the second step matters (reorg.c, read; the effect on this function measured, the rest a hypothesis): a
`bnez` is predicted taken, so `fill_eager_delay_slots` takes the slot's instruction from the branch target, and a
target that is not owned (two paths reach the label) offers only its first instruction. The address load is a
two-instruction `lui`/`addiu` pair that cannot go in a slot; with the byte's zero-extension (`andi`) first at the
label, the slot gets it, the label moves past it, and the pair follows it as in the target. A widening copy at the
label makes the zero-extension the first instruction there, ahead of the load, whatever order the scheduler gives.

Offered when a block holds `TYPE v = SIMPLE;` (a number, a symbol, `&symbol`, optionally plus a number) before a
label, with a `goto` to that label from outside the block and `v` unused before the label. Two children, the
faithful one first: every such initialiser set at the label; and that with the label's own `x = n * K;` (n a
narrow local or parameter) reading an `int` copy of n made first at the label.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'label_entry_initializer'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
LABEL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<name>{IDENT}):[ \t]*(?!:)')
TYPE = rf'(?:(?:const|unsigned|signed|struct|volatile)\s+)*{IDENT}'
DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{TYPE}(?:\s*\*+\s*|\s+))(?P<var>{IDENT})\s*=\s*(?P<rhs>[^;{{}}=\n]+?)\s*;[ \t]*$')
SIMPLE = re.compile(rf'\(?[ \t]*(?:\([^()]*\)\s*)?&?\s*{IDENT}(?:\s*[+-]\s*{NUMBER})?\s*\)?|{NUMBER}')
SCALE = re.compile(rf'(?P<lhs>{IDENT})\s*=\s*(?P<narrow>{IDENT})\s*\*\s*(?P<k>{NUMBER})\s*;')
NARROW = r'(?:u8|s8|u16|s16|char|short|unsigned\s+char|signed\s+char|unsigned\s+short)'
NOT_LABELS = {'case', 'default', 'public', 'private', 'protected'}


def _python_block_start(clean, at, lo):
    """The `{` of the innermost block around `at`, no earlier than `lo`; None when there is none."""
    depth = 0
    for pos in range(at - 1, lo - 1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                return pos
            depth -= 1
    return None


_block_start = _python_block_start
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block_start(clean, at, lo):
        found = _scan.enclosing_open(clean, at, lo, None)
        return _python_block_start(clean, at, lo) if found is NotImplemented else found


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for label in LABEL.finditer(clean, opening, end):
        label_name = label['name']
        if label_name in NOT_LABELS or re.match(r'\s*(?:\?|:)', clean[label.end():label.end() + 2]):
            continue
        gotos = [m.start() for m in re.finditer(rf'\bgoto\s+{label_name}\s*;', clean[opening:end])]
        block = _block_start(clean, label.start(), opening + 1)
        block_end = close(clean, block, '{', '}') if block is not None else None
        if not gotos or block_end is None:
            continue
        outside = [g for g in gotos if not block <= opening + g < block_end]
        if not outside or len(outside) != len(gotos):
            continue  # a goto from inside the block starts after the initialiser: only outside jumps skip it
        moved = []
        for decl in DECL.finditer(clean, block + 1, label.start()):
            var, rhs = decl['var'], decl['rhs']
            between = clean[block + 1:decl.start()]
            if decl['type'].strip() in ('return', 'goto', 'else') or between.count('{') != between.count('}'):
                continue
            if clean[decl.start():label.start()].count('{') != clean[decl.start():label.start()].count('}'):
                continue
            if not SIMPLE.fullmatch(rhs.strip()) or re.search(rf'{IDENT}\s*\(', rhs):
                continue
            if re.search(rf'\b{var}\b', clean[decl.end():label.start()]):
                continue  # read or set between the declaration and the label
            if not re.search(rf'\b{var}\b', clean[label.end():block_end]):
                continue
            moved.append(decl)
        if not moved:
            continue
        rest = re.compile(r'[^\n]*').match(clean, label.end())[0]
        indent = label['indent']
        pieces = []
        last = 0
        for decl in moved:
            pieces.append(source[last:decl.start()])
            pieces.append(f"{decl['indent']}{decl['type'].rstrip()}{'' if decl['type'].rstrip().endswith('*') else ' '}{decl['var']};")
            last = decl.end()
        pieces.append(source[last:label.end()])
        sets = [f"{d['var']} = {d['rhs'].strip()};" for d in moved]
        tail = source[label.end() + len(rest):]
        statement = source[label.end():label.end() + len(rest)]
        if statement.strip():
            first = f'{sets[0]}\n' + ''.join(f'{indent}{s}\n' for s in sets[1:]) + f'{indent}{statement.strip()}'
            body = ''.join(pieces) + first + tail
        else:
            body = ''.join(pieces) + ' ' + '\n'.join([sets[0]] + [f'{indent}{s}' for s in sets[1:]]) + tail
        children = [body]
        scale = SCALE.fullmatch(statement.strip()) if statement.strip() else None
        if scale and re.search(rf'\b{NARROW}\s+{scale["narrow"]}\b', clean[opening - 400 if opening > 400 else 0:end]):
            wide = f'{scale["narrow"]}_wide'
            if not re.search(rf'\b{wide}\b', clean[opening:end]):
                widened = body.replace(
                    f'{label_name}:' + ' ' + sets[0],
                    f'{label_name}: {wide} = {scale["narrow"]};\n{indent}{sets[0]}', 1)
                widened = widened.replace(f'{indent}{statement.strip()}', f'{indent}{scale["lhs"]} = {wide} * {scale["k"]};', 1)
                widened = _declare(widened, block, wide, indent)
                children.append(widened)
        for child in children:
            if child != source and (FAMILY, child) not in result:
                result.append((FAMILY, child))
    return result[:12]


def _declare(widened, block, wide, indent):
    """`int WIDE;` as the first line of the block that starts at `block` of the original source (it is unchanged
    up to there, since every edit comes later)."""
    after = block + 1
    newline = widened.find('\n', after)
    return widened[:newline + 1] + f'{indent}int {wide};\n' + widened[newline + 1:]
