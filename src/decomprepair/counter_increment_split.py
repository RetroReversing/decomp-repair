"""A counter advanced after the stores into its own array element: the sum taken before the last store, written after it.

The shape (KMC-era SN64 GCC, `-G0 -mips3 -O2`; a 20-instruction N64 function that pushes a value onto a global array of
8-byte elements at a global count, 60 -> 0): m2c writes the element's address from the count, the two stores through it,
and the count's increment last

    P = <array> + COUNT * 8;
    *(s8 *)(P + 4) = 0;
    *(s32 *)(P + 0) = value;
    COUNT += 1;                /* or  COUNT = COUNT + 1;  or  COUNT++;  */

and the compiler reads the count once, for the address, and increments the register it still holds after the stores.
The target reads the count a second time, after the byte store and before the word store, and stores the sum last:

    P = <array> + COUNT * 8;
    *(s8 *)(P + 4) = 0;
    next = COUNT + 1;          /* the second read of the count, ahead of the last store */
    *(s32 *)(P + 0) = value;
    COUNT = next;

The sum in a local of its own, taken between the stores and stored after the last of them, is that load order. Controls
that stay worse (measured, each 60 or worse where the target is 0): `COUNT = COUNT + 1;` ahead of the last store (120),
`COUNT += 1;` last (60), the sum taken in a second temporary (230). The reason (the compiler keeps a load it may not
share across a store it cannot prove disjoint from the count, and the sum's own load follows the byte store) is a
hypothesis; only the judge decided. The match was found by hand; this family is the part that can be repeated.

`variants` reads, in one straight-line stretch, one or more stores through a single pointer local `P` (`*P = v`,
`P->field = v`, `P[i] = v`, `M2C_FIELD(P, type *, offset) = v`, with a literal offset and a number or an unassigned
name as the value) followed directly by the count's increment (`COUNT += K;`, `COUNT -= K;`, `COUNT = COUNT + K;`,
`COUNT++;`), also when the stores sit in a `do { ... } while (0);` scaffold that the increment follows. `P` is assigned
above from an expression that reads `COUNT` (the element at the count, which is what makes the count's store
independent of the element's). The children:

- `counter_increment_split`: `next = COUNT + K;` right before the last store and `COUNT = next;` where the increment
  was (the sole store gets it too);
- `counter_increment_split_early`: the same sum before an earlier store (one child for each store ahead of the last).

Faithful and bounded: `COUNT` is a plain 32-bit global (not volatile, not a local or a parameter); the value stored
reads neither `COUNT` nor `P`; nothing but the stores and a scaffold's closing sits between the first store and the
increment; no label there; the stores are not inside a branch of their own (a closing brace other than a `do { }
while (0)` ends the stretch), so the sum is computed on every path that reaches the increment. Where the stores
cannot change the count (the element is addressed from another symbol) the program is the same one; the count is
read at a different point, which is what the target does.
"""
import re

from .counter_array_push import _fresh, _indent, _statement, _type_of
from .increment_old_value_copy import _increment, _segments
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'counter_increment_split'
EARLY = 'counter_increment_split_early'
UNWRAPPED = 'counter_increment_split_unwrapped'
FAMILIES = (FAMILY, EARLY, UNWRAPPED)
WIDE = r'(?:s32|u32|int|unsigned\s+int|unsigned|signed\s+int)'
STORES = 4
FIELD = re.compile(rf'M2C_FIELD\(\s*(?P<p>{IDENT})\s*,\s*[\w\s]+\*+\s*,\s*(?P<off>[^(),]*)\)')
CAST = re.compile(rf'\(\s*(?:const\s+)?(?:(?:unsigned|signed)\s+)?{IDENT}\s*\**\s*\)')
WHILE_ZERO = re.compile(r'while\s*\(\s*0\s*\)')
LOCAL = re.compile(rf'(?m)^[ \t]*(?:(?:static|const|unsigned|signed)\s+)*(?:[su](?:8|16|32|64)|f(?:32|64)|int|char|short|float|double|void|{IDENT})\s*(?P<stars>\**)\s*(?P<name>{IDENT})\s*(?:=[^;]*)?;')


def _store(text):
    """(pointer, value) of a store through one pointer name at literal offsets, else None."""
    parts = re.split(r'(?<![=!<>+\-*/%&|^])=(?!=)', text, maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        return None
    left, value = parts[0].strip(), parts[1].strip()
    simple = FIELD.sub(lambda hit: f'{hit["p"]} + {hit["off"]}', left)
    simple = CAST.sub('', simple)
    simple = re.sub(rf'(?:->|\.)\s*{IDENT}', '', simple)
    simple = re.sub(r'\b(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\b', '0', simple)
    names = set(re.findall(IDENT, simple))
    if len(names) != 1 or not re.fullmatch(r'[\w\s*()+\-\[\]]*', simple) or re.search(r'\[[^\]0]*\]', simple):
        return None
    if not (re.fullmatch(NUMBER, value) or re.fullmatch(IDENT, value)):
        return None
    return names.pop(), value


def _bump(text, count):
    """(sign, constant) when `text` is `count += K`, `count -= K`, `count = count + K` or `count++`, else None."""
    text = text.strip()
    hit = re.fullmatch(rf'{re.escape(count)}\s*([+-])=\s*({NUMBER})', text)
    if hit:
        return hit[1], hit[2]
    if re.fullmatch(rf'{re.escape(count)}\s*\+\+|\+\+\s*{re.escape(count)}', text):
        return '+', '1'
    hit = re.fullmatch(rf'{re.escape(count)}\s*=\s*(.+)', text, re.S)
    return _increment(hit[1], count) if hit else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    clean = part.clean
    segments = _segments(clean, part.opening + 1, part.end - 1)
    head = re.search(rf'\b{re.escape(name)}\s*\(([^{{}};]*)\)\s*{{', clean[:part.opening + 1])
    params = {}
    for argument in (head[1].split(',') if head else []):
        word = re.search(rf'({IDENT})\s*(?:\[[^\]]*\])?\s*$', argument.strip())
        if word:
            params[word[1]] = '*' in argument
    local = {hit['name']: bool(hit['stars']) for hit in LOCAL.finditer(clean, part.opening + 1, part.end)}
    context = source + '\n' + header
    out, seen = [], set()
    for index, (begin, stop, mark) in enumerate(segments):
        text = clean[begin:stop].strip()
        found = re.match(rf'(?:\+\+\s*)?({IDENT})', text) if mark == ';' else None
        if not found or found[1] in local or found[1] in params:
            continue
        count = found[1]
        step = _bump(text, count)
        ctype, array = _type_of(context, count)
        if not step or not ctype or array or not re.fullmatch(WIDE, ctype):
            continue
        for family, child in _site(source, part, segments, index, count, step, ctype, local, params):
            if child != source and child not in seen:
                seen.add(child)
                out.append((family, child))
    return out


def _site(source, part, segments, index, count, step, ctype, local, params):
    clean = part.clean
    stores, closers, at = [], 0, index - 1
    while at >= 0:
        begin, stop, mark = segments[at]
        text = clean[begin:stop].strip()
        if mark == ';' and WHILE_ZERO.fullmatch(text) and not stores and at >= 1 and segments[at - 1][2] == '}' \
                and not clean[segments[at - 1][0]:segments[at - 1][1]].strip():
            closers += 1
            at -= 2
            continue
        found = _store(text) if mark == ';' else None
        if not found:
            break
        stores.append((at, *found))
        at -= 1
    stores.reverse()
    if not stores or len(stores) > STORES:
        return []
    pointer = stores[0][1]
    if any(item[1] != pointer for item in stores) or not local.get(pointer) or pointer == count:
        return []
    for _, _, value in stores:
        if value in (count, pointer) or (re.fullmatch(IDENT, value) and value not in params and value not in local):
            return []
    first = stores[0][0]
    # P is the element at the count: its latest assignment above reads the count.
    above = clean[part.opening + 1:segments[first][0]]
    assigned = re.findall(rf'(?<![\w.>]){re.escape(pointer)}\s*=(?!=)\s*([^;]*);', above)
    if not assigned or not re.search(rf'(?<![\w.>]){re.escape(count)}\b', assigned[-1]):
        return []
    region = clean[segments[first][0]:segments[index][1]]
    if re.search(rf'(?m)^[ \t]*(?!(?:case|default)\b){IDENT}[ \t]*:(?!:)', region):
        return []
    # The count is read by nothing in the stretch but the increment itself.
    bump_text = clean[segments[index][0]:segments[index][1]]
    if len(re.findall(rf'(?<![\w.>]){re.escape(count)}\b', region)) != len(re.findall(rf'(?<![\w.>]){re.escape(count)}\b', bump_text)):
        return []
    sign, constant = step
    name = _fresh(source, 'count_next')
    lead = _indent(clean, segments[stores[0][0]][0])
    declare = (part.opening + 1, part.opening + 1, f'\n{lead if lead.strip() == "" else "    "}{ctype} {name};')
    bump = _statement(clean, segments[index])
    close = (bump[0], bump[1], f'{_indent(clean, segments[index][0])}{count} = {name};\n')
    out = []
    for position, (stored, _, _) in enumerate(stores):
        where = _statement(clean, segments[stored])[0]
        sum_line = (where, where, f'{_indent(clean, segments[stored][0])}{name} = {count} {sign} {constant};\n')
        out.append((FAMILY if position == len(stores) - 1 else EARLY, edit(source, [declare, sum_line, close])))
    unwrap = _unwrap(clean, segments, index, closers) if closers == 1 else None
    if unwrap:
        where = _statement(clean, segments[stores[-1][0]])[0]
        sum_line = (where, where, f'{_indent(clean, segments[stores[-1][0]][0])}{name} = {count} {sign} {constant};\n')
        out.append((UNWRAPPED, edit(source, [declare, sum_line, close, *unwrap])))
    return out


def _unwrap(clean, segments, index, closers):
    """Spans that delete a `do { ... } while (0);` around the stores just before the increment, or None.

    The block holds no `break`, `continue` or label, so with its closing statements gone the same code runs once."""
    closing = segments[index - 1 - closers]
    shut = closing[1]
    depth, at = 0, shut
    while at >= 0:
        char = clean[at]
        depth += (char == '}') - (char == '{')
        if depth == 0:
            break
        at -= 1
    if at <= 0 or clean[at] != '{' or not re.search(r'(?<![\w.>])do\s*$', clean[:at]):
        return None
    block = clean[at:shut]
    if re.search(r'\b(?:break|continue|goto|switch|case|default|do|while|for)\b', block) or re.search(rf'(?m)^[ \t]*{IDENT}[ \t]*:(?!:)', block):
        return None
    opening = re.search(r'do\s*$', clean[:at]).start()
    ends = segments[index - 1][1] + 1
    return [_whole_lines(clean, opening, at + 1), _whole_lines(clean, shut, ends)]


def _whole_lines(clean, begin, end):
    """(begin, end, '') widened to whole lines when only blanks flank the span."""
    line = clean.rfind('\n', 0, begin) + 1
    start = line if not clean[line:begin].strip() else begin
    tail = re.match(r'[ \t]*\n', clean[end:])
    return start, end + (tail.end() if tail and start == line else 0), ''


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 71}  # the registry: no caller wiring (registry.py)
