"""A field stored back from a local that still holds its value, written as the compound assignment it was.

The shape (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`; a 54-instruction N64 object update, 205 -> 0 with the fences
opened): a speed field is stepped, the position saved to a "previous" field and then advanced by the speed. The search's
saved best read the position into a local early and added from it

    t = *(s32 *)((char *)p + 0x1C);
    *(s32 *)((char *)p + 0x3C) += 0x7A;
    *(s32 *)((char *)p + 0x44) = t;
    *(s32 *)((char *)p + 0x1C) = t + *(s32 *)((char *)p + 0x3C);

and the target copies the position's register, loads the speed again after the store and adds in the other operand
order (two missing instructions and one register row). `*(s32 *)((char *)p + 0x1C) += *(s32 *)((char *)p + 0x3C);` is
exact. `loaded_value_compound` needs the local read only there; here it is stored elsewhere first (and reused later), and
`old_value_save_compound` needs a constant or named step. That the memory read the compound form makes is what keeps the
reload is a hypothesis; the judge decides each child.

A site is `F = t op x;` (`op` one of `+ - * & | ^`, `t op x` or, for the commutative ones, `x op t`) where the last
assignment to `t` before it is `t = F;`, and everything between the two runs straight through (only `do {` / `} while
(0);` and plain blocks), calls nothing, and writes only locals or other members of the same base: another constant
offset that does not overlap `F`, or another member name when no union is in sight. So `t` still equals `F` and the child
is the same program. `F` and `t` are 32-bit integers, and nothing named is `volatile`. The local and its other uses stay.

Offered alone (all sites, then each) and, since the saved best that needs it usually carries one-shot fences that hide
it, with every fence opened as well (`scaffold_strip.unfence`).
"""
import re

from . import scaffold_strip
from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .pattern_repairs import close

FAMILY = 'copied_field_compound'
UNFENCED = 'copied_field_compound_unfenced'
FAMILIES = (FAMILY, UNFENCED)
LIMIT = 6

WIDTHS = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2,
          'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'unsigned': 4, 'f32': 4, 'float': 4,
          's64': 8, 'u64': 8, 'f64': 8, 'double': 8}
WORD = ('s32', 'u32', 'int', 'unsigned int', 'unsigned')
BYTE = r'(?:s8|u8|char|signed\s+char|unsigned\s+char)'
CONTROL = re.compile(r'\b(?:if|else|for|switch|return|goto|break|continue|case|default|asm|__asm__)\b')
COMMUTATIVE = '+*&|^'


def _squash(text):
    return ' '.join(text.split())


def _unwrap(text):
    """`text` without redundant outer parentheses."""
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _address(text):
    """(base, offset) of `((char *) base) + K`, or None."""
    hit = re.fullmatch(rf'(?:\(\s*{BYTE}\s*\*\s*\)\s*(?P<base>{IDENT})|\(\s*\(\s*{BYTE}\s*\*\s*\)\s*(?P<base2>{IDENT})\s*\))'
                       rf'\s*\+\s*(?P<offset>{NUMBER})', _unwrap(text))
    return (hit['base'] or hit['base2'], integer(hit['offset'])) if hit else None


def _place(text):
    """(kind, base, where, type) of a memory lvalue: ('offset', base, K, T) or ('member', base, name, None)."""
    text = _unwrap(text)
    field = re.fullmatch(rf'M2C_FIELD\s*\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>[\w ]+?)\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\)', text)
    if field:
        return 'offset', field['base'], integer(field['offset']), _squash(field['type'])
    if text.startswith('*'):
        cast = re.match(r'\s*\(\s*(?P<type>[\w ]+?)\s*\*\s*\)', _unwrap(text[1:]))
        if cast:
            rest = _unwrap(text[1:])[cast.end():].strip()
            found = _address(rest) if rest.startswith('(') else None
            if found:
                return 'offset', found[0], found[1], _squash(cast['type'])
        return None
    member = re.fullmatch(rf'(?P<base>{IDENT})\s*->\s*(?P<name>{IDENT})', text)
    return ('member', member['base'], member['name'], None) if member else None


def _apart(first, other, union):
    """Whether a write to `other` cannot change `first`."""
    if not other or first[0] != other[0] or first[1] != other[1]:
        return False
    if first[0] == 'member':
        return first[2] != other[2] and not union
    if first[3] not in WIDTHS or other[3] not in WIDTHS:
        return False
    return first[2] + WIDTHS[first[3]] <= other[2] or other[2] + WIDTHS[other[3]] <= first[2]


def _assignment(text):
    """(left, compound operator or '', right) of one assignment statement without its `;`."""
    depth = 0
    for at, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char != '=' or depth:
            continue
        if text[at - 2:at] in ('<<', '>>'):
            return text[:at - 2].strip(), text[at - 2:at], text[at + 1:].strip()
        if text[at + 1:at + 2] == '=' or text[at - 1:at] in ('=', '!', '<', '>'):
            return None
        op = text[at - 1] if text[at - 1:at] and text[at - 1] in '+-*/%&|^' else ''
        return text[:at - len(op)].strip(), op, text[at + 1:].strip()
    return None


def _calls(text):
    """Whether `text` calls a function (casts, sizeof and M2C_FIELD are not calls)."""
    return any(hit[1] not in ('M2C_FIELD', 'sizeof') for hit in re.finditer(rf'\b({IDENT})\s*\(', text))


def _pure(text):
    return not (_calls(text) or re.search(r'\+\+|--(?!>)|(?<![=!<>])=(?!=)|\bvolatile\b', text))


def _statements(clean, start, end):
    """(start, stop) of every simple statement in clean[start:end]; None when something other than a straight run of
    statements, blocks and one-shot loops is there."""
    spans, at, begin, depth = [], start, start, 0
    while at < end:
        char = clean[at]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and char in '{};':
            text = clean[begin:at].strip()
            if char == ';':
                if text and not re.fullmatch(r'while\s*\(\s*0\s*\)', text):
                    spans.append((begin + len(clean[begin:at]) - len(clean[begin:at].lstrip()), at))
            elif text and text != 'do':
                return None
            begin = at + 1
        at += 1
    return spans


def _plain_blocks(clean, opening, begin, start):
    """Whether every block around `begin` that closes before `start` is a plain block or a one-shot loop: otherwise the
    load of the local may not have run."""
    stack = []
    for at in range(opening, start):
        if clean[at] == '{':
            stack.append(at)
        elif clean[at] == '}':
            if not stack:
                return False
            brace = stack.pop()
            if brace < begin < at:
                head = clean[opening:brace].rstrip()
                if head.endswith('do') and re.match(r'\s*while\s*\(\s*0\s*\)\s*;', clean[at + 1:]):
                    continue
                if not head or head[-1] not in ';{}':
                    return False
    return True


def _local(body, name):
    """The 32-bit integer type `name` is declared with inside the function, or None."""
    hit = re.search(rf'(?<![\w])(?P<type>unsigned int|unsigned|s32|u32|int)\s+{re.escape(name)}\s*;', body)
    return hit['type'] if hit else None


def _operands(right):
    """(operator, first, second) of a top-level binary operation, with an integer cast on the whole taken off."""
    right = _unwrap(right)
    cast = re.match(r'\(\s*(?:s32|u32|int|unsigned int|unsigned)\s*\)\s*', right)
    if cast and right[cast.end():].startswith('(') and close(right, cast.end(), '(', ')') == len(right):
        right = _unwrap(right[cast.end():])
    depth, found = 0, []
    for at, char in enumerate(right):
        depth += (char in '([') - (char in ')]')
        if depth or at == 0:
            continue
        if char in '?:<>=/%,':
            if char == '>' and right[at - 1] == '-':
                continue
            return None
        if char in '+-*&|^' and right[at - 1] not in '+-*&|^(' and right[at - 1:at + 1] != '->' and right[at:at + 2] != '->':
            before = right[:at].rstrip()
            if before and before[-1] not in '+-*&|^' and right[at + 1:at + 2] not in ('&', '|', '+', '-', '='):
                found.append(at)
    # a `*` right after a cast is a dereference, not a product
    found = [at for at in found if not re.search(r'\(\s*[\w ]+\**\s*\)\s*$', right[:at])]
    if len(found) != 1:
        return None
    at = found[0]
    return right[at], right[:at].strip(), right[at + 1:].strip()


def _sites(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    if re.search(r'^\s*#', clean[part.opening:part.end], re.M):
        return []
    union = bool(re.search(r'\bunion\b', clean + _blank(header)))
    body = clean[part.opening:part.end]
    sites = []
    stores = re.finditer(r'[^;{}]+;', clean[part.opening + 1:part.end - 1])
    for hit in stores:
        start = part.opening + 1 + hit.start() + len(hit[0]) - len(hit[0].lstrip())
        stop = part.opening + 1 + hit.end()
        store = _assignment(clean[start:stop - 1].strip())
        if not store or store[1]:
            continue
        field, _, right = store
        place = _place(field)
        operation = _operands(right) if place else None
        if not operation or (place[0] == 'offset' and place[3] not in WORD) or not _pure(field) or not _pure(right):
            continue
        op, first, second = operation
        for local, other in ((first, second), (second, first)):
            if local == second and op not in COMMUTATIVE:
                continue
            if not re.fullmatch(IDENT, local) or not _local(body, local) or re.search(rf'\b{local}\b', other):
                continue
            if re.search(rf'&\s*{local}\b(?!\s*(?:->|\.|\[))', body):
                continue
            loads = [m for m in re.finditer(rf'(?<![\w.>])(?:{local}\s*(?:[+\-*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{local}\b|{local}\s*(?:\+\+|--))',
                                            clean[part.opening:start])]
            if not loads:
                continue
            begin = part.opening + loads[-1].start()
            finish = clean.find(';', begin)
            load = _assignment(clean[begin:finish].strip())
            if not load or load[1] or load[0] != local:
                continue
            value = re.sub(r'^\(\s*(?:s32|u32|int)\s*\)\s*', '', _unwrap(load[2]))
            if _place(value) != place:
                continue
            between = _statements(clean, finish + 1, start)
            if (between is None or CONTROL.search(clean[finish + 1:start])
                    or not _plain_blocks(clean, part.opening, begin, start) or not all(
                    _harmless(clean[a:b].strip(), place, local, body, union) for a, b in between)):
                continue
            # the text written is the source's own spelling of both sides
            text = f'{source[start:start + len(field)]} {op}= {_spelled(source, start, stop, other)};'
            sites.append((start, stop, text))
            break
    return sites


def _spelled(source, start, stop, other):
    """The operand as the source writes it (blanked comments keep positions, so find it in the statement)."""
    statement = source[start:stop]
    at = statement.rfind(other)
    return statement[at:at + len(other)] if at >= 0 else other


def _harmless(text, place, local, body, union):
    """Whether this statement between the load and the store leaves `F`, the local and the base alone."""
    if _calls(text):
        return False
    done = _assignment(text)
    if not done:
        return not re.search(r'\+\+|--(?!>)', text)
    left, _, right = done
    if re.search(r'\+\+|--(?!>)|(?<![=!<>])=(?!=)', right):
        return False
    if re.fullmatch(IDENT, left):
        return left not in (local, place[1]) and bool(re.search(rf'\b[A-Za-z_]\w*[\s*]+{re.escape(left)}\s*;', body))
    return _apart(place, _place(left), union)


def _children(source, name, header):
    sites = _sites(source, name, header)
    if not sites:
        return []
    choices = ([sites] if len(sites) > 1 else []) + [[site] for site in sites]
    return [edit(source, chosen) for chosen in choices[:LIMIT]]


def variants(source, name, header=''):
    results, seen = [], {source}

    def add(family, text):
        if text not in seen:
            seen.add(text)
            results.append((family, text))

    for text in _children(source, name, header):
        add(FAMILY, text)
    opened = scaffold_strip.unfence(source, name)
    if opened and opened != source:
        for text in _children(opened, name, header)[:1]:
            add(UNFENCED, text)
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 90}  # the registry: no caller wiring (registry.py)
