"""A byte offset added to a pointer to an unknown (word) table symbol, read at the width the target loads.

m2c declares a table it could not type as one word and keeps its address in a pointer of that type, then adds an offset
that already counts bytes:

    extern M2C_UNK D_80100000;
    M2C_UNK *base;                                      extern u16 D_80100000[];
    base = &D_80100000;                                 ...
    x = *((i * 4) + base);                       ->     x = D_80100000[i * 2];
    y = *(((i * 4) | 2) + base);                        y = D_80100000[(i * 2) + 1];

C scales the offset by the pointer's four bytes again (`sll 4` where the target has `sll 2`) and loads a word where the
target has `lhu`. The width is read off the target's own loads, followed through the register that holds the table's
address (there is no `%lo` load). `word_symbol_byte_offset` takes only `&SYM` written in the sum and keeps the word
width; `asm_address_read_width` takes only reads already cast to a word. Two spellings are offered:
- bytes: `*(u16 *) ((u8 *) base + (i * 4))`;
- elements: the symbol declared as an array of the loaded type and indexed, when every use of it is such a read.
On a 157-instruction N64 effect update (SN64 GCC, `-O2 -mips3`) the machine draft went 2635 -> 1975 with the bytes and
2635 -> 1845 with the elements. The exact judge decides each child."""
import re

from .asm_symbol_read_width import _address_widths
from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'word_table_pointer_sum'
FAMILIES = (FAMILY,)
LIMIT = 6
_DECLARATION = re.compile(r'(?m)^[ \t]*extern\s+(?:s32|u32|int|M2C_UNK)\s+(?P<name>[A-Za-z_]\w*)\s*;')
_SIZE = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2}


def _outer(text):
    """`text` without the parentheses around all of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _split(text, operator):
    """The two sides of the only top-level `operator` in `text`, or None."""
    depth, found = 0, []
    for at, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if (not depth and char == operator and text[at - 1:at] != operator and text[at + 1:at + 2] not in (operator, '=', '>')):
            found.append(at)
    return (text[:found[0]].strip(), text[found[0] + 1:].strip()) if len(found) == 1 else None


def _scaled(offset):
    """(index, stride, add) for `I * k`, `I << n` and either one `| c` or `+ c`; None otherwise."""
    offset, add = _outer(offset), 0
    for operator in '|+':
        sides = _split(offset, operator)
        if sides and re.fullmatch(NUMBER, sides[1]):
            offset, add = _outer(sides[0]), int(sides[1].rstrip('uUlL'), 0)
            break
    for operator, spelled in (('*', r'\*'), ('<', r'<<')):
        hit = re.fullmatch(rf'(?P<index>{IDENT}|\(.*\))\s*{spelled}\s*(?P<by>{NUMBER})', offset, re.S)
        if not hit or (hit['index'].startswith('(') and close(hit['index'], 0) != len(hit['index'])):
            continue
        by = int(hit['by'].rstrip('uUlL'), 0)
        if operator == '<' and by > 29:
            return None
        stride = by if operator == '*' else 1 << by
        if stride <= 0 or add >= stride:
            return None
        return hit['index'], stride, add
    return None


def _holders(part, symbol):
    """{spelling: the assignment's span or None} for `&SYM` and each local only ever set to it."""
    found = {}
    body_start = part.opening + 1
    for hit in re.finditer(rf'(?m)^[ \t]*(?P<local>{IDENT})\s*=\s*&\s*{symbol}\s*;[ \t]*\n',
                           part.clean[:part.end]):
        if hit.start() < body_start:
            continue
        local = hit['local']
        assigned = re.findall(rf'(?<![\w.>*]){local}\s*(?:=(?!=)|\+=|-=|\+\+|--)|&\s*{local}\b', part.body)
        if len(assigned) == 1:
            found[local] = hit.span()
    return found


def _reads(part, symbol, holders):
    """(start, stop, holder spelling, offset text) for each plain read through `offset + holder`."""
    clean = part.clean
    names = '|'.join([rf'&\s*{symbol}\b'] + [rf'{local}\b' for local in holders])
    found = []
    for star in re.finditer(r'\*\s*(?=\()', clean[:part.end]):
        if star.start() <= part.opening:
            continue
        before = clean[part.opening:star.start()].rstrip()
        if before[-1:] not in '=(,;{}+-*/&|^<>!?:' and not before.endswith('return'):
            continue
        stop = close(clean, star.end())
        if not stop or re.match(r'\s*(?:(?:<<|>>|[-+*/%&|^])?=(?!=)|\+\+|--|\[|\.|->)', clean[stop:]):
            continue
        inner = clean[star.end() + 1:stop - 1]
        sides = _split(_outer(inner), '+')
        if not sides:
            continue
        for held, offset in (sides, sides[::-1]):
            spelled = _outer(held)
            if re.fullmatch(names, spelled):
                found.append((star.start(), stop, '&' + symbol if spelled.startswith('&') else spelled, _outer(offset)))
                break
    return found


def _bytes(part, width, reads):
    return [(start, stop, f'*({width} *) ((u8 *) {holder} + ({offset}))') for start, stop, holder, offset in reads]


def _elements(part, symbol, width, declaration, holders, reads):
    """The symbol as an array of the loaded type, when each of its uses is one of `reads`."""
    size, edits, used = _SIZE[width], [], set()
    for start, stop, holder, offset in reads:
        scaled = _scaled(offset)
        if not scaled or scaled[1] % size or scaled[2] % size:
            return None
        index, stride, add = scaled
        by, plus = stride // size, add // size
        element = index if by == 1 else f'{index} * {by}'
        if plus:
            element = f'({element}) + {plus}' if by != 1 else f'{element} + {plus}'
        edits.append((start, stop, f'{symbol}[{element}]'))
        used.add(holder)
    inside = [(start, stop) for start, stop, _, _ in reads] + [span for span in holders.values()]
    for mention in re.finditer(rf'\b(?:{"|".join([symbol, *holders])})\b', part.clean[:part.end]):
        at = mention.start()
        if declaration.start() <= at < declaration.end() or any(start <= at < stop for start, stop in inside):
            continue
        local = mention[0]
        if local in holders and re.search(r'\*\s*$', part.clean[:at]) and part.clean[mention.end():].lstrip()[:1] == ';':
            continue  # (its own declaration)
        return None
    edits.append((declaration.start(), declaration.end(), f'extern {width} {symbol}[];'))
    for local, span in holders.items():
        edits.append((*span, ''))
        line = re.search(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*\*\s*{local}\s*;[ \t]*\n', part.clean[:part.end])
        if line and line.start() > part.opening:
            edits.append((*line.span(), ''))
    return edits


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    widths = _address_widths(asm)
    byte_groups, element_groups = [], []
    for declaration in _DECLARATION.finditer(part.clean):
        symbol = declaration['name']
        width = widths.get(symbol)
        if width not in _SIZE:
            continue
        holders = _holders(part, symbol)
        # (an offset that counts elements is not scaled by a constant: only m2c's byte counts are taken)
        reads = [read for read in _reads(part, symbol, holders) if _scaled(read[3])]
        if not reads:
            continue
        byte_groups.append(_bytes(part, width, reads))
        if edits := _elements(part, symbol, width, declaration, holders, reads):
            element_groups.append(edits)
    children = []
    for groups in (element_groups, byte_groups):
        if len(groups) > 1:
            children.append(edit(source, sorted(change for edits in groups for change in edits)))
        children += [edit(source, sorted(edits)) for edits in groups]
    return [(FAMILY, child) for child in dict.fromkeys(children) if child != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
