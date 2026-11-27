"""The temporaries m2c splits a chained assignment (and a compound update) into, written back.

The shape (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`; a small N64 object update, matched from a saved best).
The game wrote `p->c = p->b = p->a = x;` and read the member back, and `p->phase += K;`; m2c and the searches on its
draft spell them as

    v = *(u16 *)((char *)p + 0x14) + 0x21;
    *(s16 *)((char *)p + 0x12) = v;
    t = *(s16 *)((char *)p + 0x12);
    ...
    *(u16 *)((char *)p + 0x14) = (u16) v;
    *(s16 *)((char *)p + 0x16) = v;

    w = *(s32 *)((char *)p + 0x30) + 0x400;
    *(s32 *)((char *)p + 0x30) = w;
    *(s8 *)((char *)p + 0x63) = ~(w >> 8);
    *(s8 *)((char *)p + 0x62) = ~(w >> 8);
    *(s8 *)((char *)p + 0x61) = ~(w >> 8);

Five rewrites, each a family:

- `scattered_store_chain`: several stores of one local to members of one base, with unrelated statements between,
  written as one chain at the first store (the first store innermost, so the stores keep their order); and, when the
  local is used nowhere else, with its value written in the chain.
- `expression_store_chain`: adjacent stores of the same computed expression, written as one chain.
- `staged_field_compound`: `w = F op k; F = w;` as `F op= k;`, the local's later reads as `F`.
- `dead_value_store_chain`: `t = E; u = ...; A = t; B = t;` with `t` not read afterwards, written `B = A = E;` (an N64
  voice allocator, KMC GCC 2.7.2: the draft reused one local for a priority and then a script pointer, and with the
  second value written in the chain, after guarded_exit_for_loop and callee_arity_trim, the function was exact).
- `member_reread_local`: after `t = F;`, the later reads of `F` written `t`, until `F` could change (the target keeps
  the value in the saved register it read it into, instead of reloading the member).

A chain moves stores earlier, so everything they pass must be a plain assignment with no call whose memory accesses
are all members of the same base at constant offsets that overlap none of the moved ones; anything else declines.
Offered per family (all sites together) and all together, with and without the re-read, with the one-shot fences
opened and kept: the saved best's steps were no better alone. That the chain is what the game wrote is a hypothesis; the judge decides.
"""
import re

from . import scaffold_strip
from .csource import _blank, find
from .line_scan import mentions
from .pattern_repairs import close

SCATTERED = 'scattered_store_chain'
EXPRESSION = 'expression_store_chain'
COMPOUND = 'staged_field_compound'
REREAD = 'member_reread_local'
TOGETHER = 'split_store_chain'
DEAD = 'dead_value_store_chain'
FAMILIES = (SCATTERED, EXPRESSION, COMPOUND, REREAD, TOGETHER, DEAD)
LIMIT = 9

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
WIDTHS = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4, 'float': 4}
ACCESS = re.compile(
    rf'\*\s*\(\s*(?P<type>\w+)\s*\*\s*\)\s*\(\s*\(\s*(?:char|s8|u8)\s*\*\s*\)\s*(?:\(\s*(?P<paren>{IDENT})\s*\)|'
    rf'(?P<base>{IDENT}))\s*\+\s*(?P<offset>{NUMBER})\s*\)'
    rf'|M2C_FIELD\s*\(\s*(?P<mbase>{IDENT})\s*,\s*(?P<mtype>\w+)\s*\*\s*,\s*(?P<moffset>{NUMBER})\s*\)')
OTHER_MEMORY = re.compile(r'->|\[|\.\s*[A-Za-z_]|\*\s*\(|(?:^|[=(,+\-*/&|^~!<>?:])\s*\*\s*[A-Za-z_]|&\s*[A-Za-z_(]|\+\+|--')
CALL = re.compile(rf'\b(?!M2C_FIELD\b|sizeof\b){IDENT}\s*\(')
LINE = re.compile(r'[ \t]*(?P<lhs>[^;{}=]+?)\s*(?P<op>(?:[-+*/%&|^]|<<|>>)?=)(?!=)\s*(?P<rhs>[^;{}]+);[ \t]*')
CONTROL = re.compile(r'\b(?:if|else|for|while|switch|return|goto|break|continue|case|default|do|asm|__asm__)\b')


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _hit(match):
    kind = match['type'] or match['mtype']
    width = WIDTHS.get(kind)
    if width is None:
        return None
    return (match['paren'] or match['base'] or match['mbase'], int(match['offset'] or match['moffset'], 0), width)


def _accesses(text):
    """[(base, offset, width)] of every memory access in `text`, or None when one can't be read."""
    found = []
    for match in ACCESS.finditer(text):
        place = _hit(match)
        if place is None:
            return None
        found.append(place)
    rest = ACCESS.sub(' v ', text)
    return None if OTHER_MEMORY.search(rest) or CALL.search(rest) else found


def _place(text):
    """The member an lvalue is, or None."""
    match = ACCESS.fullmatch(_unwrap(text))
    return _hit(match) if match else None


def _overlap(a, b):
    return a[1] < b[1] + b[2] and b[1] < a[1] + a[2]


def _statements(source, name):
    """The function's lines as (start, end, parsed-or-None), end past the newline; `parsed` for plain assignments."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    if re.search(r'\bvolatile\b|(?m:^\s*#)', clean[span[0]:span[1]]):
        return []
    position, found = clean.find('{', span[0]) + 1, []
    while 0 < position < span[1]:
        newline = clean.find('\n', position)
        end = len(clean) if newline < 0 else newline + 1
        text = clean[position:end].rstrip('\n')
        match = LINE.fullmatch(text)
        parsed = None
        if match and not CONTROL.search(text) and _accesses(text) is not None:
            parsed = {key: (match[key], position + match.start(key), position + match.end(key))
                      for key in ('lhs', 'op', 'rhs')}
        found.append((position, end, parsed))
        position = end
    return found


def _passes(parsed, moved):
    """Whether a store to the members `moved` may be taken above the statement `parsed`: it reads and writes only locals
    and other members of their base, and doesn't move the base."""
    if parsed is None or parsed['lhs'][0].strip() == moved[0][0]:
        return False
    text = f"{parsed['lhs'][0]} {parsed['op'][0]} {parsed['rhs'][0]}"
    return all(base == moved[0][0] and not any(_overlap((base, offset, width), place) for place in moved)
               for base, offset, width in _accesses(text))


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _indent(source, start):
    return source[start:len(source) - len(source[start:].lstrip(' \t'))]


def _chain(targets, value):
    return ' = '.join([*reversed(targets), value]) + ';\n'


def _compatible(places):
    return (len({(base, width) for base, _, width in places}) == 1
            and not any(_overlap(a, b) for i, a in enumerate(places) for b in places[i + 1:]))


def _scattered(source, name, inline):
    lines = _statements(source, name)
    clean = _blank(source)
    edits, taken = [], set()

    def stored(parsed):
        if not parsed or parsed['op'][0] != '=' or _place(parsed['lhs'][0]) is None:
            return None
        value = re.fullmatch(rf'(?:\(\s*(?:s8|u8|s16|u16|s32|u32)\s*\)\s*)?(?P<name>{IDENT})', _unwrap(parsed['rhs'][0]))
        return value['name'] if value else None

    for index, (start, _, parsed) in enumerate(lines):
        local = stored(parsed)
        if local is None or index in taken:
            continue
        places, sites = [_place(parsed['lhs'][0])], [index]
        for later in range(index + 1, len(lines)):
            other = lines[later][2]
            if other is None or re.fullmatch(rf'\s*{local}\s*', other['lhs'][0]):
                break
            place = _place(other['lhs'][0]) if stored(other) == local else None
            if place and _compatible([*places, place]):
                # every statement since the first store must let this one go above it
                between = [lines[i][2] for i in range(index + 1, later) if i not in sites]
                if all(_passes(item, [place]) for item in between):
                    places.append(place)
                    sites.append(later)
        if len(sites) < 2:
            continue
        targets = [source[lines[i][2]['lhs'][1]:lines[i][2]['lhs'][2]] for i in sites]
        value = source[parsed['rhs'][1]:parsed['rhs'][2]]
        remove = []
        if inline and index:
            before_start, before_end, before = lines[index - 1]
            uses = len(re.findall(rf'(?<![\w.>]){local}\b', clean[slice(*find(source, name))]))
            # its declaration, its one definition and these stores
            if before and before['op'][0] == '=' and before['lhs'][0].strip() == local and uses == len(sites) + 2:
                value = source[before['rhs'][1]:before['rhs'][2]]
                remove = [(before_start, before_end, '')]
        if inline and not remove:
            continue
        taken.update(sites)
        edits += remove
        edits.append((start, lines[index][1], _indent(source, start) + _chain(targets, value)))
        edits += [(lines[i][0], lines[i][1], '') for i in sites[1:]]
    return _apply(source, edits)


def _expression(source, name):
    lines = _statements(source, name)
    edits, index = [], 0
    while index < len(lines):
        start, end, parsed = lines[index]
        index += 1
        if not parsed or parsed['op'][0] != '=' or _place(parsed['lhs'][0]) is None:
            continue
        value = _unwrap(parsed['rhs'][0])
        if re.fullmatch(rf'-?\s*(?:{IDENT}|{NUMBER}[uUfF]?)', value):
            continue  # a name or a literal: paired_store_chain and constant_store_chain write those
        group = [lines[index - 1]]
        while index < len(lines):
            other = lines[index][2]
            if not (other and other['op'][0] == '=' and _place(other['lhs'][0])
                    and ' '.join(_unwrap(other['rhs'][0]).split()) == ' '.join(value.split())):
                break
            group.append(lines[index])
            index += 1
        if len(group) < 2:
            continue
        places = [_place(item[2]['lhs'][0]) for item in group]
        if not _compatible(places) or any(base != places[0][0] or any(_overlap((base, offset, width), p) for p in places)
                                          for base, offset, width in _accesses(value)):
            continue
        targets = [source[item[2]['lhs'][1]:item[2]['lhs'][2]] for item in group]
        edits.append((start, group[-1][1],
                      _indent(source, start) + _chain(targets, source[parsed['rhs'][1]:parsed['rhs'][2]])))
    return _apply(source, edits)


def _compound(source, name):
    lines = _statements(source, name)
    span = find(source, name)
    if not span:
        return source
    clean = _blank(source)
    for index in range(len(lines) - 1):
        (start, _, first), (_, store_end, second) = lines[index], lines[index + 1]
        if not first or not second or first['op'][0] != '=' or second['op'][0] != '=':
            continue
        local = first['lhs'][0].strip()
        place = _place(second['lhs'][0])
        if not re.fullmatch(IDENT, local) or place is None or place[2] != 4 or second['rhs'][0].strip() != local:
            continue
        value = re.fullmatch(rf'(?P<field>.+?)\s*(?P<op>[-+*&|^])\s*(?P<step>{NUMBER})', _unwrap(first['rhs'][0]))
        if not value or _place(value['field']) is None or _place(value['field'])[:2] != place[:2]:
            continue
        if not re.search(rf'\b(?:s32|u32|int)\s+{local}\s*;', clean[span[0]:span[1]]):
            continue
        # every later read of the local must come before the next write to it or the member, in this straight run
        reads, last = [], index + 1
        for later in range(index + 2, len(lines)):
            item = lines[later]
            parsed = item[2]
            if parsed is None or parsed['lhs'][0].strip() == local:
                break
            reads += [(item[0] + m.start(), item[0] + m.end())
                      for m in re.finditer(rf'(?<![\w.>]){local}\b', clean[item[0]:item[1]])]
            last = later
            written = _place(parsed['lhs'][0])
            if written and (written[0] != place[0] or _overlap(written, place)):
                break
        used = len(re.findall(rf'(?<![\w.>]){local}\b', clean[span[0]:span[1]]))
        stopped = lines[last + 1][2] if last + 1 < len(lines) else None
        redefined = stopped is not None and stopped['lhs'][0].strip() == local
        if used != len(reads) + 3 and not redefined:  # declaration, definition, store
            continue
        member = _unwrap(source[second['lhs'][1]:second['lhs'][2]])
        edits = [(start, store_end, f"{_indent(source, start)}({member}) {value['op']}= {value['step']};\n")]
        edits += [(a, b, f'({member})') for a, b in reads]
        return _compound(_apply(source, edits), name)
    return source


def _reread(source, name):
    """After `t = F;` (a local as wide as the member or an int), later reads of `F` in the straight run as `t`, up to a
    write that could change either."""
    lines = _statements(source, name)
    span = find(source, name)
    if not span:
        return source
    clean = _blank(source)
    edits, taken = [], []
    for index, (_, _, parsed) in enumerate(lines):
        if not parsed or parsed['op'][0] != '=' or not re.fullmatch(IDENT, parsed['lhs'][0].strip()):
            continue
        local, place = parsed['lhs'][0].strip(), _place(parsed['rhs'][0])
        declared = re.search(rf'\b(s16|u16|s32|u32|int|s8|u8)\s+{local}\s*;', clean[span[0]:span[1]])
        if place is None or not declared or WIDTHS[declared[1]] < place[2]:
            continue
        member = ' '.join(_unwrap(parsed['rhs'][0]).split())
        for later in range(index + 1, len(lines)):
            start, end, item = lines[later]
            if item is None or item['lhs'][0].strip() in (local, place[0]):
                break
            for match in ACCESS.finditer(clean, item['rhs'][1], item['rhs'][2]):
                if ' '.join(source[match.start():match.end()].split()) == member and match.start() not in taken:
                    taken.append(match.start())
                    edits.append((match.start(), match.end(), local))
            written = _place(item['lhs'][0])
            if written and (written[0] != place[0] or _overlap(written, place)):
                break
    return _apply(source, edits)


def _dead_value(source, name):
    """`t = E; [u = ...;] A = t; B = t;` where `t` is not read afterwards, written `B = A = E;` at the stores. The
    value's other lives keep the local: a reused temporary (the draft's name for the priority, then for a script
    pointer) no longer carries the second value, which moved the register the first one gets."""
    lines = _statements(source, name)
    span = find(source, name)
    if not span:
        return source
    clean = _blank(source)
    opening = clean.find('{', span[0])
    for index in range(1, len(lines) - 1):
        parsed = lines[index][2]
        if not parsed or parsed['op'][0] != '=' or _place(parsed['lhs'][0]) is None:
            continue
        local = parsed['rhs'][0].strip()
        if not re.fullmatch(IDENT, local):
            continue
        places, last = [], index
        while last < len(lines):
            item = lines[last][2]
            if not (item and item['op'][0] == '=' and item['rhs'][0].strip() == local and _place(item['lhs'][0])):
                break
            places.append(_place(item['lhs'][0]))
            last += 1
        if len(places) < 2 or not _compatible(places) or places[0][2] != 4 or any(p[0] == local for p in places):
            continue
        if not re.search(rf'\b(?:s32|u32|int)\s+{local}\s*;', clean[span[0]:span[1]]):
            continue
        # the definition: above the stores, past plain assignments to other locals only
        at, moved = index - 1, []
        while at >= 0:
            text = clean[lines[at][0]:lines[at][1]].strip()
            if re.match(rf'{local}\s*=(?!=)', text):
                break
            other = re.fullmatch(rf'({IDENT})\s*=(?!=)\s*([^;{{}}=]+);', text)
            if not other or mentions(text, local) or CALL.search(other[2]) or re.search(r'\+\+|--', other[2]):
                at = -1
                break
            moved.append(other[1])
            at -= 1
        if at < 0:
            continue
        definition = re.fullmatch(rf'[ \t]*{local}\s*=\s*(?P<value>[^;{{}}=]+);\s*', clean[lines[at][0]:lines[at][1]])
        if not definition:
            continue
        a, b = lines[at][0] + definition.start('value'), lines[at][0] + definition.end('value')
        value = clean[a:b]
        if (CALL.search(value) or re.search(r'\+\+|--', value) or mentions(value, local)
                or any(mentions(value, other) for other in moved)):
            continue
        # not read again: nothing names it after the stores, and no loop or jump can bring control back to a read
        if mentions(clean[lines[last - 1][1]:span[1]], local) or _in_loop(clean, opening, lines[at][0]):
            continue
        if re.search(r'\bgoto\b', clean[opening:span[1]]):
            continue
        targets = [source[lines[i][2]['lhs'][1]:lines[i][2]['lhs'][2]] for i in range(index, last)]
        edits = [(lines[at][0], lines[at][1], ''),
                 (lines[index][0], lines[last - 1][1], _indent(source, lines[index][0]) + _chain(targets, source[a:b]))]
        return _apply(source, edits)
    return source


def _in_loop(clean, opening, position):
    """Whether `position` is inside a loop's braces."""
    stack = []
    for hit in re.finditer(r'[{}]', clean[opening:position]):
        if hit[0] == '{':
            head = clean[opening:opening + hit.start()].rstrip()
            looped = re.search(r'\bdo$', head) is not None
            if head.endswith(')'):
                depth, at = 0, len(head)
                while at > 0:
                    at -= 1
                    depth += (head[at] == ')') - (head[at] == '(')
                    if depth == 0:
                        break
                looped = re.search(r'\b(?:for|while)\s*$', head[:at]) is not None
            stack.append(looped)
        elif stack:
            stack.pop()
    return any(stack)


def variants(source, name):
    """[(family, source)]: each rewrite alone, the three together, and the three with the fences opened."""
    result, seen = [], {source}

    def offer(family, text):
        if text not in seen:
            seen.add(text)
            result.append((family, text))

    def every(text, reread):
        text = _scattered(text, name, inline=True)
        text = _scattered(text, name, inline=False)
        text = _expression(_compound(text, name), name)
        return _reread(text, name) if reread else text

    opened = scaffold_strip.unfence(source, name)
    for reread in (True, False):  # (the reread pays off only with the local widened: offered with and without it)
        for text in (opened, source):
            if text and every(text, reread) != text:
                offer(TOGETHER, every(text, reread))
    offer(SCATTERED, _scattered(source, name, inline=True))
    offer(SCATTERED, _scattered(source, name, inline=False))
    offer(EXPRESSION, _expression(source, name))
    offer(COMPOUND, _compound(source, name))
    offer(REREAD, _reread(source, name))
    result = result[:LIMIT]
    offer(DEAD, _dead_value(source, name))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 57}
