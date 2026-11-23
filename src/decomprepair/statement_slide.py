"""One simple statement of a straight-line run moved past the independent statements around it.

GCC 2.7.2's first scheduler works backward from the end of a basic block and breaks ties by the original order, and the
register allocator numbers pseudos by first use, so the order of independent statements in one run decides which constant
is materialised first, where a load sits among its siblings and which pseudo wins a tie. m2c emits a run in the order
its own pass met the instructions, which is rarely the order the game's source had. Two slides decided a 132-instruction
table search (KMC `-O2`): `flags |= 0x80800;` after the statement that computes the division (the `lui 0x51eb` pair then
precedes the `lui 8` pair, 295 -> 255), and the halfword reload that stores the high byte moved up beside the first load
(255 -> 195 -> 135 with the byte load first). Each alone moved the judge's score, so a greedy chain finds them one at a time
once something offers the slide.

A child is offered only when the moved statement commutes with every statement it passes: no call, no store through a
pointer other than an `M2C_FIELD(base, type *, offset)` (compared by base, byte interval), no shared local that one writes
and the other touches. The move is a hypothesis for the scheduler; the judge decides. Bounded to `LIMIT` children,
shortest slides first.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'statement_slide'
FAMILIES = (FAMILY,)
LIMIT = 40
REACH = 4
FIELD = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>[^,*]+?)\s*\*\s*,\s*(?P<off>0[xX][0-9a-fA-F]+|\d+)\s*\)')
WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'int': 4}
TYPES = r'(?:s8|u8|s16|u16|s32|u32|f32|int|char|short|long|unsigned|signed)'
CALL = re.compile(rf'\b(?!{TYPES}\b)[A-Za-z_]\w*\s*\(')
CAST_POINTER = re.compile(rf'\(\s*(?:{TYPES}\s*)+\*+\s*\)')
DEREF = re.compile(r'(?:^|[-+*/&|^<>=?:(,!~])\s*\*')
OTHER = re.compile(r'\[|->|\.|\+\+|--|\bvolatile\b')


def _effects(text):
    """`(writes, reads)` as sets of ('v', name) and ('f', base, lo, hi) keys, or None when the statement is no plain
    assignment of locals and `M2C_FIELD` cells."""
    depth, split = 0, None
    for pos, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == '=' and depth == 0 and text[pos - 1:pos] not in '=!<>+-*/&|^%' and text[pos + 1:pos + 2] != '=':
            split = pos
            break
    if split is None:
        return None
    left, right = text[:split], text[split + 1:]
    stripped = CAST_POINTER.sub(' ', FIELD.sub(' ', left + ' = ' + right))
    if CALL.search(stripped) or DEREF.search(stripped) or OTHER.search(stripped) or '&' in left:
        return None
    def keys(part):
        out = set()
        for found in FIELD.finditer(part):
            low = int(found['off'], 0)
            out.add(('f', found['base'], low, low + WIDTH.get(found['type'].strip(), 4)))
            out.add(('v', found['base']))
        out |= {('v', ident) for ident in re.findall(rf'\b{IDENT}\b', FIELD.sub(' ', part))
                if ident not in WIDTH and ident not in {'unsigned', 'signed', 'short', 'long', 'void', 'M2C_FIELD'}}
        return out
    lhs_field = FIELD.fullmatch(left.strip())
    writes = {('f', lhs_field['base'], int(lhs_field['off'], 0), int(lhs_field['off'], 0) + WIDTH.get(lhs_field['type'].strip(), 4))} if lhs_field else keys(left)
    reads = keys(right) | (({('v', lhs_field['base'])}) if lhs_field else set())
    return writes, reads


def _clash(a, b):
    for x in a:
        for y in b:
            if x[0] == 'v' and y[0] == 'v' and x[1] == y[1]:
                return True
            if x[0] == 'f' and y[0] == 'f' and x[1] == y[1] and x[2] < y[3] and y[2] < x[3]:
                return True
    return False


def commutes(one, two):
    first, second = _effects(one), _effects(two)
    if not first or not second:
        return False
    return not (_clash(first[0], second[0] | second[1]) or _clash(second[0], first[1]))


def _runs(clean, start, end):
    """Maximal runs of consecutive simple `...;` statements, as `[(from, to, [(s, e), ...])]` at one block level."""
    runs = []
    stack = [[]]
    i = start
    while i < end:
        char = clean[i]
        if char == '{':
            stack.append([])
            i += 1
        elif char == '}':
            runs.append(stack.pop())
            i += 1
        elif char.isspace():
            i += 1
        else:
            stop = i
            depth = 0
            while stop < end:
                c = clean[stop]
                depth += (c in '([') - (c in ')]')
                if depth == 0 and c in ';{}':
                    break
                stop += 1
            if stop < end and clean[stop] == ';':
                text = clean[i:stop]
                if re.match(r'(?:if|for|while|do|else|switch|return|goto|case|default)\b', text) or ':' in text.replace('?', '').replace('::', ''):
                    runs.append(stack[-1])
                    stack[-1] = []
                else:
                    stack[-1].append((i, stop + 1))
                i = stop + 1
            else:
                runs.append(stack[-1])
                stack[-1] = []
                i = stop if stop > i else i + 1
    runs.append(stack[0])
    return [run for run in runs if len(run) >= 3]


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    found = []
    for run in _runs(part.clean, part.opening + 1, part.clean.rindex('}', part.opening, part.end)):
        texts = [source[s:e] for s, e in run]
        for index, text in enumerate(texts):
            for step in range(1, REACH + 1):
                for sign in (1, -1):
                    target = index + sign * step
                    if not 0 <= target < len(texts):
                        continue
                    lo, hi = sorted((index, target))
                    between = [texts[k] for k in range(lo, hi + 1) if k != index]
                    if all(commutes(text, other) for other in between):
                        order = list(range(len(texts)))
                        order.insert(target, order.pop(index))
                        pieces = [source[run[k][0]:run[k][1]] for k in order]
                        child = source[:run[0][0]]
                        for k, piece in enumerate(pieces):
                            gap = source[run[k - 1][1]:run[k][0]] if k else ''
                            child += gap + piece
                        child += source[run[-1][1]:]
                        found.append((step, child))
    result = []
    for _, child in sorted(found, key=lambda item: item[0]):
        if child != source and child not in result:
            result.append(child)
        if len(result) >= LIMIT:
            break
    return [(FAMILY, child) for child in result]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
