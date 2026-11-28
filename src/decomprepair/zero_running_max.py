"""m2c's `x > 0U` where the target compares a running maximum that still holds zero, written against the maximum.

    best = 0;                                            if (flag != 0 && score > best) {
    if ((flag != 0) && (score > 0U)) { best = score; }       best = score;
                                                         }

The game's first candidate is compared like every later one (`score > best`). m2c knows `best` is zero there and prints
the constant, but gcc then folds `score > 0U` into `score != 0` (`beqz`), while the target keeps `sltu` against the
register that holds the zero. An SN-N64 GCC 2.8.1 leader banner of 242 instructions picks the highest of up to four
scores this way, twice; both `sltu`s were missing with the constant.

The same bytes also showed the other half of the zero: the target copies it (`move $a0, $a2`) from the leader's index,
set to 0 just before the maximum, where m2c had left `leader = 0;` far above, over a guarded block and a label. With the
two initialisations adjacent, cse makes the second a copy of the first.

Offered when `EXPR > 0U` guards a block that assigns EXPR to a local last assigned 0 before the test. All such tests
change in one child; a second child also moves down, to just before each maximum's `= 0;`, another local's `= 0;` that
nothing in between names (and whose gotos in between all land in between). The two compares are equal while the local is zero; a candidate only, the judge decides.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'zero_running_max'
FAMILIES = (FAMILY,)

_IDENT = r'[A-Za-z_]\w*'
_IF = re.compile(r'\bif\s*\(')
_ZERO = re.compile(r'>\s*0[uU]\b')


def _space(text):
    return re.sub(r'\s+', '', text)


def _left(clean, start, operator):
    """Where the left operand of the comparison at `operator` begins: after the unmatched `(` that encloses it."""
    depth = 0
    for at in range(operator - 1, start - 1, -1):
        if clean[at] == ')':
            depth += 1
        elif clean[at] == '(':
            if depth == 0:
                return at + 1
            depth -= 1
        elif depth == 0 and clean[at - 1:at + 1] in ('&&', '||'):
            return at + 1
    return None


def _sinks(source, clean, low, maxima):
    """Edits moving an earlier `other = 0;` line to just before each maximum's `= 0;` line."""
    edits, taken = [], set()
    for local, test in maxima:
        own = list(re.finditer(rf'(?m)^([ \t]*){local} = 0;[ \t]*\n', clean[:test]))
        if not own or own[-1].start() < low:
            continue
        here = own[-1]
        for other in reversed(list(re.finditer(rf'(?m)^[ \t]*({_IDENT}) = 0;[ \t]*\n', clean[:here.start()]))):
            name = other[1]
            if other.start() < low or other.start() in taken:
                break
            between = clean[other.end():here.start()]
            if not between.strip() or re.search(rf'(?<![\w.>]){name}(?!\w)', between):
                continue
            if any(not re.search(rf'(?m)^\s*{label}\s*:', between) for label in re.findall(r'\bgoto\s+(\w+)', between)):
                continue
            taken.add(other.start())
            edits.append((other.start(), other.end(), ''))
            edits.append((here.start(), here.start(), f'{here[1]}{name} = 0;\n'))
            break
    return edits


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, low, high = part.clean, part.opening, part.end
    edits, maxima = [], []
    for test in _IF.finditer(clean, low, high):
        opened = test.end() - 1
        closed = close(clean, opened)
        brace = re.compile(r'\s*\{').match(clean, closed + 1) if closed >= 0 else None
        if not brace:
            continue
        block = clean[brace.end() - 1:close(clean, brace.end() - 1, '{', '}') + 1]
        for zero in _ZERO.finditer(clean, opened, closed):
            begin = _left(clean, opened, zero.start())
            if begin is None:
                continue
            compared = clean[begin:zero.start()].strip()
            value = re.sub(r'^\(\s*(?:u32|unsigned(?:\s+int)?)\s*\)\s*', '', compared)
            for stored in re.finditer(rf'(?<![\w.>])({_IDENT})\s*=(?!=)\s*([^;=]+);', block):
                local, right = stored[1], re.sub(r'^\(\s*(?:u32|s32|unsigned(?:\s+int)?|int)\s*\)\s*', '', stored[2])
                if _space(right) != _space(value):
                    continue
                before = re.findall(rf'(?<![\w.>]){local}\s*([-+*/|&^]?=(?!=)\s*[^;]*|\+\+|--);', clean[low:test.start()])
                if before and _space(before[-1]) == '=0':
                    edits.append((zero.start(), zero.end(), f'> (u32) {local}'))
                    maxima.append((local, test.start()))
                    break
    if not edits:
        return []
    out = [(FAMILY, edit(source, edits))]
    sunk = _sinks(source, clean, low, maxima)
    if sunk:
        out.insert(0, (FAMILY, edit(source, edits + sunk)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
