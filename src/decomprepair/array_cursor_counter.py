"""A pointer walked through a global array only on some passes, written as the array indexed by a counter of its own.

m2c, and a hand search that started from it, keep an output list as a pointer the loop steps when it emits an element:

    Vtx *pos = gVtx;                      s32 n = 0;
    u8 *colour = gColour;                 s32 c = 0;
    for (...) {                           for (...) {
        if (live) {                           if (live) {
            pos->x = x;                           gVtx[n].x = x;
            *colour++ = r;                        gColour[c++] = r;
            pos++;                                n++;
        }                                     }
    }                                     }

The two compile differently. With the pointers written by hand they are ordinary induction variables, set where the
source set them. Written through counters, the loop pass makes the pointers itself (strength reduction), sets them up in
the preheader after the invariants it has moved there, and removes the counters; its own count of the loop's instructions
is also the one that decides which invariants move. Measured on an 87-instruction N64 particle update (SN GCC 2.8.1,
`-G0 -mips3 -O2 -mfp64`): the pointer form kept a second global's `lui` hoisted into a saved register the target does not
spend and gave one cursor a derived pointer at 1929; both cursors as counters was exact. `pointer_walk_to_index` needs a
counter stepped once on every pass beside the pointer; here there is none, so one is introduced.

Offered when the pointer is a local of the array's own element type, every plain assignment to it is the array's start
(`p = G;`, `p = &G[0];`), it is first set before it is read, and its address is never taken: then `p == G + p_index` at
every point, so each step moves to the counter and each use is the array at the counter. All such pointers together first,
then each alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'array_cursor_counter'
FAMILIES = (FAMILY,)
MAX_CURSORS = 6

ID = r'[A-Za-z_]\w*'
DECL = re.compile(
    rf'(?<=[;{{}}])(?P<lead>\s*)(?P<type>(?:(?:struct|union|unsigned|signed)\s+)?{ID})(?:\s+|(?=\*))\*\s*(?P<name>{ID})'
    rf'(?P<init>\s*=\s*[^;,{{}}]+)?\s*;'
)
NOT_TYPES = {'return', 'goto', 'else', 'case', 'do', 'sizeof'}


def _start(value, element):
    """The array `value` is the first element of: `G`, `&G[0]`, either behind a cast to the element's pointer."""
    value = value.strip()
    cast = re.match(rf'\(\s*{re.escape(element)}\s*\*\s*\)\s*', value)
    if cast:
        value = value[cast.end():]
    found = re.fullmatch(rf'&\s*({ID})\s*\[\s*0\s*\]|({ID})', value)
    return (found[1] or found[2]) if found else None


def _array_of(text, array, element):
    """Whether `text` declares `array` as a one-dimensional array of exactly `element`."""
    kind = r'\s+'.join(map(re.escape, element.split()))
    return bool(re.search(
        rf'(?m)(?:^|(?<=[;{{}}]))[ \t]*(?:(?:extern|static)\s+)?{kind}\s+{re.escape(array)}\s*\[[^\]\[]*\]\s*[;=]', text))


def _plan(body, clean, declared, found):
    """(edits, counter) rewriting the pointer of declaration `found` in the function's text, or None."""
    pointer, element = found['name'], ' '.join(found['type'].split())
    if element in NOT_TYPES:
        return None
    word = re.escape(pointer)
    counter = f'{pointer}_index'
    if re.search(rf'\b{re.escape(counter)}\b', clean):
        return None
    if re.search(rf'(?<![&\w])&\s*{word}\b(?!\s*(?:\[|->))|\bsizeof\s*\(?\s*{word}\b', clean):
        return None
    init = found['init']
    after = [m for m in re.finditer(rf'(?<![\w.]){word}\b', clean) if m.start() >= found.end()]
    if any(clean[:m.start()].rstrip().endswith('->') for m in after):
        return None
    array = None
    if init:
        array = _start(init.split('=', 1)[1], element)
        if not array:
            return None
    elif not after or not re.match(rf'{word}\s*=(?!=)', clean[after[0].start():]):
        return None
    edits, stepped, resume = [], False, 0
    for use in after:
        at, end = use.start(), use.end()
        if at < resume:
            return None
        before, rest = clean[:at].rstrip(), clean[end:]
        statement = before.endswith((';', '{', '}', ')', ':')) or before.endswith('else') or before.endswith(' do')
        assign = re.match(r'\s*=(?!=)\s*([^;]*);', rest)
        if assign and statement:
            step = re.match(rf'{word}\b\s*([+-])', assign[1])
            if step:
                inner = end + assign.start(1)
                edits += [(at, end, counter), (inner, inner + len(pointer), counter)]
                resume, stepped = inner + len(pointer), True
                continue
            start = _start(body[end + assign.start(1):end + assign.end(1)], element)
            if not start or (array and start != array):
                return None
            array = start
            edits.append((at, end + assign.end(), f'{counter} = 0;'))
            continue
        if re.match(r'\s*[+\-]=', rest) or re.match(r'\s*(?:\+\+|--)', rest):
            edits.append((at, end, None))
            stepped = True
            continue
        if before.endswith(('++', '--')):
            edits.append((at, end, counter))
            stepped = True
            continue
        edits.append((at, end, None))
    if not array or not stepped or not _array_of(declared, array, element):
        return None
    if re.search(rf'(?<=[;{{}}])\s*{ID}[\s*]+{re.escape(array)}\b', clean):
        return None
    out = []
    for at, end, text in edits:
        if text is not None:
            out.append((at, end, text))
            continue
        before, rest = clean[:at].rstrip(), clean[end:]
        post = re.match(r'\s*(\+\+|--)', rest)
        compound = re.match(r'\s*[+\-]=', rest)
        dereference = re.search(r'\*\s*(\(\s*)?$', clean[:at])
        if compound:
            if not (before.endswith((';', '{', '}', ')', ':')) or before.endswith('else')):
                return None
            out.append((at, end, counter))
        elif post:
            tail = rest[post.end():]
            if tail.lstrip().startswith(';') and before.endswith((';', '{', '}', ')', ':', 'else')) and not dereference:
                out.append((at, end, counter))
            elif tail.lstrip().startswith('->'):
                arrow = end + post.end() + tail.index('->')
                out.append((at, arrow + 2, f'{array}[{counter}{post[1]}].'))
            elif dereference and (not dereference[1] or tail.lstrip().startswith(')')):
                stop = end + post.end()
                if dereference[1]:
                    stop += tail.index(')') + 1
                out.append((dereference.start(), stop, f'{array}[{counter}{post[1]}]'))
            else:
                out.append((at, end + post.end(), f'({array} + {counter}{post[1]})'))
        elif rest.lstrip().startswith('->'):
            out.append((at, end + rest.index('->') + 2, f'{array}[{counter}].'))
        elif rest.lstrip().startswith('['):
            opening = end + rest.index('[')
            closing = close(clean, opening, '[', ']')
            if closing is None or clean[closing - 1] != ']' or re.search(rf'\b{word}\b', clean[opening:closing]):
                return None
            closing -= 1
            if body[opening + 1:closing].strip() == '0':
                out.append((at, closing + 1, f'{array}[{counter}]'))
            else:
                out += [(at, opening + 1, f'{array}[{counter} + ('), (closing, closing + 1, ')]')]
        elif dereference and not dereference[1]:
            out.append((dereference.start(), end, f'{array}[{counter}]'))
        else:
            out.append((at, end, f'({array} + {counter})'))
    zero = ' = 0' if init else ''
    out.append((found.start('type'), found.end(), f'int {counter}{zero};'))
    return out


def _apply(text, edits):
    for at, end, new in sorted(edits, reverse=True):
        text = text[:at] + new + text[end:]
    return text


def _rewrite(source, name, pointer, header):
    span = find(source, name)
    if not span:
        return None
    body = source[span[0]:span[1]]
    clean = _blank(body)
    found = next((m for m in DECL.finditer(clean) if m['name'] == pointer), None)
    if not found:
        return None
    declared = _blank(header) + '\n' + _blank(source[:span[0]])
    # the initialiser is read from the real text; the declaration was found in the blanked one
    found = DECL.match(body, found.start()) or found
    edits = _plan(body, clean, declared, found)
    return source[:span[0]] + _apply(body, edits) + source[span[1]:] if edits else None


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source[span[0]:span[1]])
    if not re.search(r'\b(?:for|while|do|goto)\b', clean):
        return []
    pointers = [m['name'] for m in DECL.finditer(clean)]
    alone = []
    for pointer in pointers:
        child = _rewrite(source, name, pointer, header)
        if child:
            alone.append((pointer, child))
        if len(alone) == MAX_CURSORS:
            break
    out = []
    if len(alone) > 1:
        together = source
        for pointer, _ in alone:
            together = _rewrite(together, name, pointer, header) or together
        out.append((FAMILY, together))
    out += [(FAMILY, child) for _, child in alone]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
