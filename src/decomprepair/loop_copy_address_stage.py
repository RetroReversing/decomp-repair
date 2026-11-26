"""A record copy loop's source address, staged part by part inside the loop.

m2c (and a hand draft) sets the source pointer before the loop, `src = (u16 *) ((table + 0x64) + player * 0x178 +
(id & 0xFF) * 0x12); for (i = 0; i < 8; i++) { dst[i] = src[i]; }`. Under `-O1` gcc 2.7.2 then computes the address before
it takes the destination's address, and adds the scaled terms in the wrong order. The game's code computes the
destination's address first, then the first scaled term, the other index, the table's address, and adds the table to the
first term before the second: the order loop.c leaves the invariants of a body that names each part in its own local,

    { u16 *d = &dst[i]; int a = player * 0x178; int b = id & 0xFF; char *base = table + 0x64;
      *d = ((u16 *) (b * 0x12 + (a + (int) base)))[i]; }

One function of 61 instructions went from a register-only near miss to exact with it. The reading of loop.c (movables are
moved in the body's order) is a hypothesis; the judge decides.

The rewrite only fires when it cannot change behaviour: the loop's whole body is the copy, the address is a sum of one
byte-array symbol, literal offsets and two scaled terms of locals or parameters (never globals, which the copy could
alias), and the pointer is not read again before it is next assigned. One child for each of the two terms placed first.
"""
import re

from .arm_block_support import IDENT, brace_pairs, local_declaration, statements
from .csource import _blank
from .integer_repair_support import NUMBER, edit, view

FAMILY = 'loop_copy_address_stage'
FAMILIES = (FAMILY,)

BYTE = r'(?:char|unsigned\s+char|signed\s+char|u8|s8)'
CAST = r'(?:\(\s*(?:u8|s8|u16|s16|u32|s32|int|short|char|unsigned\s+(?:char|short|int)|signed\s+char)\s*\)\s*)'
ASSIGN = re.compile(rf'(?P<ptr>{IDENT})\s*=(?!=)\s*(?P<addr>[^;{{}}]+);')
HEAD = re.compile(rf'for\s*\(\s*(?P<i>{IDENT})\s*=\s*0\s*;\s*(?P=i)\s*<\s*(?P<n>{NUMBER})\s*;\s*'
                  rf'(?:(?P=i)\s*\+\+|\+\+\s*(?P=i)|(?P=i)\s*\+=\s*1)\s*\)')
LEAF = rf'(?:\(\s*{IDENT}\s*&\s*{NUMBER}\s*\)|{IDENT}\s*&\s*{NUMBER}|{CAST}?{IDENT})'


def _unwrapped(text):
    """A loop body without its braces and `do { } while (0)` wrappers."""
    text = text.strip()
    while True:
        inner = re.fullmatch(r'do\s*\{(.*)\}\s*while\s*\(\s*0\s*\)\s*;?', text, re.S)
        if inner is None:
            inner = re.fullmatch(r'\{(.*)\}', text, re.S)
        if inner is None:
            return text
        text = inner[1].strip()


def _closed(text):
    """True when the parenthesis that opens `text` is the one that closes it."""
    depth = 0
    for at, char in enumerate(text):
        depth += {'(': 1, ')': -1}.get(char, 0)
        if depth == 0:
            return at == len(text) - 1
    return False


def _terms(text):
    """The terms of a sum, through any parentheses."""
    text = text.strip()
    while text.startswith('(') and text.endswith(')') and _closed(text):
        text = text[1:-1].strip()
    parts, depth, last = [], 0, 0
    for at, char in enumerate(text):
        depth += {'(': 1, ')': -1}.get(char, 0)
        if char == '+' and depth == 0:
            parts.append(text[last:at])
            last = at + 1
    if not parts:
        return [text]
    parts.append(text[last:])
    return [term for part in parts for term in _terms(part)]


def _address(addr, element, byte_arrays, names):
    """(symbol, literal offset, [(operand, scale), (operand, scale)]) of a byte-address sum cast to `element *`."""
    cast = re.match(rf'\(\s*{re.escape(element)}\s*\*\s*\)\s*', addr)
    if not cast:
        return None
    symbol, offset, scaled = None, 0, []
    for term in _terms(addr[cast.end():]):
        if term in byte_arrays and symbol is None:
            symbol = term
        elif re.fullmatch(NUMBER, term):
            offset += int(term.rstrip('uUlL'), 0)
        else:
            product = re.fullmatch(rf'(?P<x>.+?)\s*\*\s*(?P<k>{NUMBER})', term, re.S)
            if not product:
                return None
            operand = product['x'].strip()
            if operand.startswith('(') and _closed(operand) and re.fullmatch(LEAF, operand[1:-1].strip()):
                operand = operand[1:-1].strip()
            if not re.fullmatch(LEAF, operand):
                return None
            used = [word for word in re.findall(rf'(?<![\w])(?<!0x){IDENT}', re.sub(CAST + r'|\b' + NUMBER, ' ', operand))]
            if len(used) != 1 or used[0] not in names:
                return None
            scaled.append((operand, product['k']))
    if symbol is None or len(scaled) != 2:
        return None
    return symbol, offset, scaled


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    context = _blank(header or '') + '\n' + clean[:part.opening]
    byte_arrays = set(re.findall(rf'(?m)^[ \t]*extern\s+{BYTE}\s+({IDENT})\s*\[\s*\w*\s*\]\s*;', context))
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs or not byte_arrays or any(re.search(r'\bstage_' + word + r'\b', clean) for word in ('dst', 'first', 'second', 'base')):
        return []
    signature = clean[clean.rfind(name, 0, part.opening):part.opening]
    parameters = set(re.findall(rf'({IDENT})\s*(?=[,)])', signature))
    out = []
    for block_open, block_close in sorted(pairs.items()):
        spans = statements(clean, block_open + 1, block_close)
        for (start, end), (loop_start, loop_end) in zip(spans, spans[1:]):
            assign = ASSIGN.fullmatch(clean[start:end].strip())
            if not assign:
                continue
            pointer = assign['ptr']
            declared = local_declaration(clean, part.opening, pointer)
            if not declared or declared[1] != '*':
                continue
            element = declared[0]
            loop = _unwrapped(clean[loop_start:loop_end])
            head = HEAD.match(loop)
            if not head or int(head['n'].rstrip('uUlL'), 0) > 128:
                continue
            index = head['i']
            at = rf'{CAST}*(?:\(\s*)?{CAST}*{index}(?:\s*\))?'
            copy = re.fullmatch(rf'(?P<dst>{IDENT})\s*\[\s*{at}\s*\]\s*=\s*{pointer}\s*\[\s*{at}\s*\]\s*;',
                                _unwrapped(loop[head.end():]))
            if not copy or copy['dst'] == pointer:
                continue
            if not re.search(rf'(?m)^[ \t]*extern\s+{re.escape(element)}\s+{copy["dst"]}\s*\[\s*\w*\s*\]\s*;', context):
                continue
            later = re.search(rf'\b{pointer}\b', clean[loop_end:part.end])
            if later and not re.match(rf'{pointer}\s*=(?!=)', clean[loop_end + later.start():]):
                continue
            names = {word for word in parameters if word != index}
            names |= {word for word in re.findall(rf'\b{IDENT}\b', assign['addr'])
                      if word != index and local_declaration(clean, part.opening, word)}
            address = _address(assign['addr'].strip(), element, byte_arrays, names)
            if not address:
                continue
            symbol, offset, scaled = address
            if re.search(rf'&\s*(?:{"|".join(names) or "$^"})\b', clean[part.opening:part.end]):
                continue
            header_text = HEAD.search(source, loop_start, loop_end)
            if not header_text:
                continue
            pad = re.match(r'[ \t]*', source[source.rfind('\n', 0, loop_start) + 1:loop_start])[0]
            inner = pad + '  '
            base = f'{symbol} + {offset:#x}' if offset else symbol
            for first, second in (scaled, scaled[::-1]):
                factor = f'({first[0]})' if '&' in first[0] else first[0]
                body = (f'{header_text[0]}\n{pad}{{\n'
                        f'{inner}{element} *stage_dst = &{copy["dst"]}[{index}];\n'
                        f'{inner}int stage_first = {factor} * {first[1]};\n'
                        f'{inner}int stage_second = {second[0]};\n'
                        f'{inner}char *stage_base = (char *) {base};\n'
                        f'{inner}*stage_dst = (({element} *) (stage_second * {second[1]} + (stage_first + (int) stage_base)))[{index}];\n'
                        f'{pad}}}')
                text = edit(source, [(start, end, ''), (loop_start, loop_end, body)])
                if text != source and (FAMILY, text) not in out:
                    out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 92}  # the registry: no caller wiring (registry.py)
