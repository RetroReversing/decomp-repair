"""A script-op handler's operand reads and its destination write, as private inline helpers, with the rest of the steps that pay off only together.

A script-op handler (148 instructions, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) reads two operands and writes the
result back through the same kind of operand: a flag selects a call, otherwise an index is masked and read from (or
stored to) a 16-entry register file or a global table, and the result is clamped to a `s16`. m2c spells the three
accesses as long ladders with its temporaries, and its saved best sat at 1005 (rechecked 1135) after 27,000 automatic
trials. `operand_read_helper` never fired on it: that family reads the scaffolded spelling or a plain `idx &= mask`
ladder, not m2c's `temp = word >> 0x10;` preludes, `temp * 2` scaled indices or `((i + 1) - 1) <= (16 - 1)` limits,
and nothing wrote the store half as a helper. What the match needed (1135 -> 0; the sibling handler that had a
matched helper showed the idea) is four edits that each alone score the same or worse (measured on the match: the
helpers without the other three 865, the clamp left as it was 320, the write's flag and index passed as expressions
instead of locals 1830, the flag local masked 654):

- Each read is `X = read_operand(p, sel, idx)`, one `static __inline__ s32` helper with a local `value` returned, its
  flag and index `u8` parameters. The flag and the index are the site's own expressions, the preludes that only fed
  them gone (`temp = word; temp2 = temp >> 0x10;` folded into the arguments). The inlined parameters are set before the
  first branch, which is the target's block order.
- The store half is one `static __inline__ void write_operand(p, sel, idx, s16 v)` the same way. Its flag and index
  reach it as two `u32` locals made first (the flag *not* masked: the mask belongs to the `u8` parameter): a local
  keeps the word's two shifts in separate pseudos, so the copy the inline makes for the index survives next to its
  source. An expression there is folded by cse into one pseudo and the second block of the target never appears.
- The dispatch carrier goes: a `u8` local that only ever receives `param & 0xFF` and is compared or switched on is
  the expression itself. Its two assignments made the allocator hold a second copy of the parameter.
- The clamp's polarity: `if (r >= -0x8000) { n = max; if (r <= max) n = r; } else n = min;`. Written the other way
  round reorg fills the first branch from the other side and the pair of branches the target has never forms.

Offered, per function: `operand_access_helpers` (the reads alone, the reads and the write), `operand_access_bundle`
(the reads, the write and the carrier, each with either clamp polarity). The judge decides; none is a verdict. Nothing
here is scaffolding: every edit is a plain spelling a developer could have written.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'operand_access_helpers'
BUNDLE = 'operand_access_bundle'
FAMILIES = (FAMILY, BUNDLE)
READ = 'read_operand'
WRITE = 'write_operand'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'
FF = r'0[xX][fF][fF]'


class Node:
    """A statement: `simple` (text up to its `;`), `block`, `if` (cond, then, els) or `opaque` (switch, loops)."""

    def __init__(self, kind, start, end, **fields):
        self.kind, self.start, self.end = kind, start, end
        self.__dict__.update(fields)


def _skip(clean, i):
    while i < len(clean) and clean[i].isspace():
        i += 1
    return i


def _python_simple_end(clean, i, end):
    depth = 0
    while i < end:
        ch = clean[i]
        depth += ch in '([{'
        depth -= ch in ')]}'
        if ch == ';' and depth <= 0:
            return i + 1
        i += 1
    return None


_simple_end = _python_simple_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _simple_end(clean, i, end):
        found = _scan.statement_end_nonpositive(clean, i, end)
        return _python_simple_end(clean, i, end) if found is NotImplemented else found


def _statement(clean, i, end):
    """(Node, next position) of the statement at `i`, or None."""
    i = _skip(clean, i)
    if i >= end:
        return None
    if clean[i] == '{':
        stop = close(clean, i, '{', '}')
        if not stop or stop > end:
            return None
        node = Node('block', i, stop, items=_list(clean, i + 1, stop - 1))
        return (node, stop) if node.items is not None else None
    word = re.match(r'(if|switch|while|for)\b\s*\(', clean[i:end])
    if word:
        paren = i + word.end() - 1
        stop = close(clean, paren, '(', ')')
        if word[1] != 'if' and stop and clean[_skip(clean, stop)] == '{':
            brace = _skip(clean, stop)
            after = close(clean, brace, '{', '}')
            return (Node('opaque', i, after), after) if after else None
        body = _statement(clean, stop, end) if stop else None
        if not body:
            return None
        child, after = body
        if word[1] != 'if':
            return Node('opaque', i, after), after
        other, ahead = None, after
        probe = _skip(clean, after)
        if re.match(r'else\b', clean[probe:end]):
            chained = _statement(clean, probe + 4, end)
            if not chained:
                return None
            other, ahead = chained
        return Node('if', i, ahead, cond=clean[paren + 1:stop - 1].strip(), then=child, els=other), ahead
    if re.match(r'do\b', clean[i:end]):
        body = _statement(clean, i + 2, end)
        if not body:
            return None
        tail = re.compile(r'\s*while\s*\(').match(clean, body[1], end)
        stop = close(clean, tail.end() - 1, '(', ')') if tail else None
        after = _simple_end(clean, stop, end) if stop else None
        return (Node('opaque', i, after), after) if after else None
    stop = _simple_end(clean, i, end)
    return (Node('simple', i, stop, text=clean[i:stop]), stop) if stop else None


def _list(clean, i, end):
    items = []
    while True:
        i = _skip(clean, i)
        if i >= end:
            return items
        got = _statement(clean, i, end)
        if not got:
            return None
        items.append(got[0])
        i = got[1]


def _flat(node):
    if node is None:
        return []
    if node.kind == 'block':
        return [leaf for item in node.items for leaf in _flat(item)]
    return [node]


def _assign(node):
    """(lhs, rhs) of a plain `name = expression;`, or None."""
    if node.kind != 'simple':
        return None
    found = re.fullmatch(rf'\s*({IDENT})\s*=\s*([^=].*?)\s*;', node.text, re.S)
    return (found[1], found[2]) if found else None


def _norm(text):
    """An expression for comparing two spellings: no space, no parenthesis, no integer cast."""
    text = re.sub(r'\(\s*(?:s32|u32|int|unsigned\s+int)\s*\)', '', text)
    return re.sub(r'[\s()]', '', text)


def _words(text, mapping):
    return re.sub(rf'\b{IDENT}\b', lambda hit: mapping.get(hit[0], hit[0]), text)


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _strip_cast(text):
    found = re.fullmatch(r'\(\s*(?:s32|u32|int|unsigned\s+int)\s*\)\s*(\(.*\))', text.strip(), re.S)
    return _unwrap(found[1]) if found and close(found[1], 0) == len(found[1]) else _unwrap(text)


def _limit(cond, index):
    """(limit as a C number, limit as an integer) of `index < N`, `index <= N - 1` and m2c's `((index + 1) - 1) <= (N - 1)`."""
    text = re.sub(r'[\s()]', '', cond)
    found = re.fullmatch(rf'{re.escape(index)}(?:\+1-1)?(<=?)({NUMBER})(-1)?', text)
    if not found:
        return None
    value = int(found[2].rstrip('uUlL'), 0) - (1 if found[3] else 0) + (1 if found[1] == '<=' else 0)
    return (found[2] if found[1] == '<' and not found[3] else f'0x{value:X}U'), value


class Site:
    """Where an operand read or the destination write sits and what its pieces are."""


def _prelude(items, at, wanted):
    """{name: expanded expression} of the plain assignments directly before items[at], and their nodes by name."""
    defs, nodes, index = {}, {}, at - 1
    run = []
    while index >= 0 and _assign(items[index]):
        run.append(items[index])
        index -= 1
    for node in reversed(run):
        name, rhs = _assign(node)
        defs[name] = _words(rhs, {key: f'({value})' for key, value in defs.items()})
        nodes[name] = node
    return defs, nodes


def _dead_after(clean, name, position, end):
    """True when `name` is not read after `position` before the function sets it again."""
    hit = re.compile(rf'\b{re.escape(name)}\b').search(clean, position, end)
    return not hit or bool(re.match(r'\s*=(?!=)', clean[hit.end():hit.end() + 4]))


def _read_site(clean, items, at, end):
    node = items[at]
    if node.kind != 'if' or not node.els:
        return None
    then = _flat(node.then)
    call = _assign(then[0]) if len(then) == 1 else None
    called = re.fullmatch(rf'({IDENT})\s*\(\s*({IDENT})\s*,\s*(.+?)\s*&\s*{FF}\s*\)', call[1], re.S) if call else None
    if not called:
        return None
    other = _flat(node.els)
    steps = [_assign(leaf) for leaf in other[:-1]] if other and other[-1].kind == 'if' else None
    result = call[0]
    copied = False
    if other and other[-1].kind == 'simple' and len(other) >= 2 and other[-2].kind == 'if':
        copied = True
        copy = _assign(other[-1])
        if not copy or copy[0] != result:
            return None
        steps, other = [_assign(leaf) for leaf in other[:-2]], other[:-1]
    if not steps or not other or other[-1].kind != 'if' or len(steps) > 2 or not all(steps):
        return None
    masked = re.fullmatch(rf'(.+?)\s*&\s*({NUMBER})', steps[0][1], re.S)
    if not masked or _norm(masked[1]) != _norm(called[3]):
        return None
    scale = None
    if len(steps) == 2:
        if not re.fullmatch(rf'{re.escape(steps[0][0])}\s*\*\s*2', steps[1][1].strip()):
            return None
        scale = steps[1][0]
    ladder = other[-1]
    arms = _flat(ladder.then), _flat(ladder.els)
    loads = [_assign(arm[0]) if len(arm) == 1 else None for arm in arms]
    if not all(loads) or loads[0][0] != loads[1][0]:
        return None
    if loads[0][0] != result and not copied:
        return None
    limit = _limit(ladder.cond, steps[0][0])
    if not limit:
        return None
    index = {steps[0][0]: 'idx'}
    if scale:
        index[scale] = '(idx * 2)'
    texts = [_strip_cast(_words(load[1], dict(index, **{called[2]: 'p'}))) for load in loads]
    defs, nodes = _prelude(items, at, None)
    expand = {key: f'({value})' for key, value in defs.items()}
    selector = re.sub(r'\s*!=\s*0\s*$', '', node.cond.strip())
    site = Site()
    site.node, site.result, site.callee, site.pointer = node, result, called[1], called[2]
    site.mask, site.limit, site.loads = masked[2], limit[0], texts
    site.select = _words(selector, expand)
    site.index = _words(called[3], expand)
    wanted = set(re.findall(IDENT, selector + ' ' + called[3]))
    site.prelude = [nodes[name] for name in nodes if name in wanted]
    site.dead = [item for item in site.prelude if _dead_after(clean, _assign(item)[0], node.end, end)]
    site.key = (site.callee, site.pointer, site.mask, site.limit) + tuple(_norm(text) for text in texts)
    return site


def _clamp(node, clean):
    """(value, narrow, low, high) of m2c's clamp of a value into a narrow local, or None."""
    found = re.fullmatch(rf'({IDENT})\s*<\s*\(?\s*(-\s*{NUMBER})\s*\)?', node.cond.strip()) if node.kind == 'if' else None
    if not found or not node.els:
        return None

    def constant(leaves, narrow):
        mapped = {}
        for leaf in leaves:
            pair = _assign(leaf)
            if not pair:
                return None
            mapped[pair[0]] = pair[1].strip()
        if narrow not in mapped:
            return None
        value = mapped[narrow]
        cast = re.fullmatch(rf'\(\s*s16\s*\)\s*({IDENT})', value)
        value = mapped.get(cast[1]) if cast else value
        return value if value and re.fullmatch(rf'\(?\s*-?\s*{NUMBER}\s*\)?', value) else None

    then = _flat(node.then)
    first = _assign(then[-1]) if then else None
    if not first:
        return None
    narrow = first[0] if not re.fullmatch(r'\(\s*s16\s*\)\s*' + IDENT, first[1]) else first[0]
    lowest = constant(then, narrow)
    rest = _flat(node.els)
    guard = rest[-1] if rest and rest[-1].kind == 'if' and not rest[-1].els else None
    if not guard or lowest is None:
        return None
    highest = constant(rest[:-1], narrow)
    given = _flat(guard.then)
    again = _assign(given[0]) if len(given) == 1 else None
    limit = re.fullmatch(rf'{re.escape(found[1])}\s*<=\s*(.+)', guard.cond.strip())
    if (highest is None or not again or again[0] != narrow or _norm(again[1]) != found[1] or not limit
            or _norm(limit[1]) != _norm(highest)):
        return None
    return found[1], narrow, lowest, highest.strip()


def _write_site(clean, items, end):
    """The destination write at the end of the function: prelude, clamp, flagged call, masked store, return."""
    if len(items) < 7 or items[-1].kind != 'simple' or not re.fullmatch(r'\s*return\b[^;]*;', items[-1].text):
        return None
    ladder = items[-2]
    stores = _flat(ladder.then) if ladder.kind == 'if' else None
    if not stores or ladder.els is None:
        return None
    count = len(items)
    cursor = count - 3
    scale = None
    if _assign(items[cursor]) and re.fullmatch(rf'{IDENT}\s*\*\s*2', _assign(items[cursor])[1].strip()):
        scale = _assign(items[cursor])[0]
        cursor -= 1
    masked = re.fullmatch(rf'\s*({IDENT})\s*&=\s*({NUMBER})\s*;', items[cursor].text) if items[cursor].kind == 'simple' else None
    if not masked:
        return None
    flagged = items[cursor - 1]
    if flagged.kind != 'if' or flagged.els:
        return None
    arm = _flat(flagged.then)
    if len(arm) != 2 or arm[1].kind != 'simple' or arm[1].text.strip() != items[-1].text.strip():
        return None
    call = re.fullmatch(rf'\s*({IDENT})\s*\(\s*({IDENT})\s*,\s*{re.escape(masked[1])}\s*&\s*{FF}\s*,\s*(?:\(\s*s16\s*\)\s*)?({IDENT})\s*\)\s*;',
                        arm[0].text, re.S)
    clamp_at = cursor - 2
    if not call or clamp_at < 1:
        return None
    clamp = _clamp(items[clamp_at], clean)
    if not clamp or clamp[1] != call[3]:
        return None
    first = clamp_at
    while first > 0 and _assign(items[first - 1]):
        first -= 1
    defs, nodes = _prelude(items, clamp_at, None)
    index = {masked[1]: 'idx'}
    if scale:
        index[scale] = '(idx * 2)'
    texts = []
    other = _flat(ladder.els)
    for leaf in (stores[0] if len(stores) == 1 else None, other[0] if len(other) == 1 else None):
        lhs = (re.fullmatch(r'\s*(.+?)\s*=\s*(?:\(\s*s16\s*\)\s*)?' + re.escape(call[3]) + r'\s*;', leaf.text, re.S)
               if leaf is not None and leaf.kind == 'simple' else None)
        if not lhs:
            return None
        texts.append(_words(lhs[1], dict(index, **{call[2]: 'p'})))
    limit = _limit(ladder.cond, masked[1])
    if not limit:
        return None
    expand = {key: f'({text})' for key, text in defs.items()}
    selector = _unwrap(re.sub(r'\s*!=\s*0\s*$', '', flagged.cond.strip()))
    selector = re.sub(rf'^\((.*)\)\s*&\s*{FF}$', r'\1', selector) if re.fullmatch(rf'\(.*\)\s*&\s*{FF}', selector) else selector
    site = Site()
    site.first, site.last = items[first], items[-2]
    site.value, site.narrow, site.low, site.high = clamp
    site.callee, site.pointer, site.mask, site.limit, site.stores = call[1], call[2], masked[2], limit[0], texts
    site.select = _words(selector, expand)
    site.index = _words(masked[1], expand)
    site.ret = items[-1].text.strip()
    site.nodes = [items[index] for index in range(first, count)]
    return site


def _declared(part, name):
    head = part.clean[:part.opening]
    signature = head[head.rindex('(') + 1:head.rindex(')')] if '(' in head else ''
    for piece in signature.split(',') + part.clean[part.opening + 1:part.end].split(';'):
        found = re.fullmatch(rf'\s*(?:register\s+)?(?P<type>(?:{IDENT}\s+)*?{IDENT})(?:\s+|\s*(?P<stars>\*+)\s*)(?P<name>{IDENT})\s*', piece)
        if found and found['name'] == name:
            return (found['type'] + (' ' + found['stars'] if found['stars'] else '')).strip(), found['stars'] or ''
    return None


def _read_helper(name, site, pointer):
    star = '' if pointer.endswith('*') else ' '
    return (f'static __inline__ s32 {name}({pointer}{star}p, u8 sel, u8 idx)\n{{\n  s32 value;\n  if (sel)\n  {{\n'
            f'    value = {site.callee}(p, idx & 0xFF);\n  }}\n  else\n  {{\n    idx &= {site.mask};\n'
            f'    if (idx < {site.limit})\n    {{\n      value = {site.loads[0]};\n    }}\n    else\n    {{\n'
            f'      value = {site.loads[1]};\n    }}\n  }}\n  return value;\n}}\n')


def _write_helper(name, site, pointer):
    star = '' if pointer.endswith('*') else ' '
    return (f'static __inline__ void {name}({pointer}{star}p, u8 sel, u8 idx, s16 v)\n{{\n  if (sel)\n  {{\n'
            f'    {site.callee}(p, idx & 0xFF, v);\n  }}\n  else\n  {{\n    idx &= {site.mask};\n'
            f'    if (idx < {site.limit})\n    {{\n      {site.stores[0]} = v;\n    }}\n    else\n    {{\n'
            f'      {site.stores[1]} = v;\n    }}\n  }}\n}}\n')


def _top(part):
    stop = close(part.clean, part.opening, '{', '}')
    return _list(part.clean, part.opening + 1, stop - 1) if stop else None


def _each(items):
    """Every (list, index) of the statement lists in the function, outermost first."""
    found = [items]
    for item in items:
        for child in _children(item):
            found.extend(_each(child))
    return found


def _children(node):
    if node.kind == 'block':
        return [node.items]
    if node.kind == 'if':
        return [(_flat_list(branch)) for branch in (node.then, node.els) if branch is not None]
    return []


def _flat_list(node):
    return node.items if node.kind == 'block' else [node]


def _reads(part):
    items = _top(part)
    if items is None:
        return None, []
    found = []
    for run in _each(items):
        for at in range(len(run)):
            site = _read_site(part.clean, run, at, part.end)
            if site:
                found.append(site)
    return items, sorted(found, key=lambda site: site.node.start)


def _carrier(part):
    """(edits) that drop a `u8` local only ever set from `param & 0xFF` and use the expression."""
    clean = part.clean
    body = clean[part.opening:part.end]
    edits = []
    for hit in re.finditer(rf'\b(?:unsigned\s+char|u8)\s+({IDENT})\s*;', body):
        name = hit[1]
        assigns = list(re.finditer(rf'(?m)^[ \t]*{re.escape(name)}\s*=\s*({IDENT})\s*&\s*{FF}\s*;[ \t]*\n?', body))
        sources = {item[1] for item in assigns}
        if not assigns or len(sources) != 1:
            continue
        origin = next(iter(sources))
        if re.search(rf'\b{re.escape(origin)}\s*(?:=(?!=)|[-+*/&|^]=|\+\+|--)', body) or not _declared(part, origin):
            continue
        removed = {(item.start(), item.end()) for item in assigns}
        declaration = (hit.start(), hit.end())
        replacement = f'({origin} & 0xFF)'
        for use in re.finditer(rf'\b{re.escape(name)}\b', body):
            span = (use.start(), use.end())
            if span in removed or any(start <= span[0] < stop for start, stop in removed) or declaration[0] <= span[0] < declaration[1]:
                continue
            edits.append((part.opening + span[0], part.opening + span[1], replacement))
        for start, stop in removed:
            edits.append((part.opening + start, part.opening + stop, ''))
        line = clean.rfind('\n', 0, part.opening + declaration[0]) + 1
        edits.append((line, part.opening + declaration[1] + (1 if clean[part.opening + declaration[1]:][:1] == '\n' else 0), ''))
        # `switch ((u32)((short) (p & 0xFF)))` is the expression itself for a byte
    return edits


def _switch_tidy(text):
    return re.sub(r'switch\s*\(\s*\(u32\)\s*\(\s*\(short\)\s*(\([^()]*\))\s*\)\s*\)', r'switch \1', text)


def _build(source, name, write, carrier, flip):
    part = view(source, name)
    if not part or re.search(r'\b(?:goto|asm|__asm__)\b', part.clean[part.opening:part.end]) or READ in source or WRITE in source:
        return None
    items, reads = _reads(part)
    if not reads or items is None:
        return None
    clean = part.clean
    texts, edits, helpers = [], [], {}
    used = set()
    for site in reads:
        pointer = _declared(part, site.pointer)
        if not pointer:
            return None
        key = site.key + (pointer[0],)
        if key not in helpers:
            if len(helpers) >= 2:
                return None
            helpers[key] = READ if not helpers else f'{READ}_2'
            texts.append(_read_helper(helpers[key], site, pointer[0]))
        edits.append((site.node.start, site.node.end, f'{site.result} = {helpers[key]}({site.pointer}, {site.select}, {site.index});'))
        used.update(re.findall(IDENT, clean[site.node.start:site.node.end]))
        for item in site.dead:
            first = clean.rfind('\n', 0, item.start) + 1
            last = item.end + 1 if clean[item.end:item.end + 1] == '\n' else item.end
            edits.append((first if not clean[first:item.start].strip() else item.start, last, ''))
            used.add(_assign(item)[0])
    tail = None
    if write:
        tail = _write_site(clean, items, part.end)
        if not tail:
            return None
        pointer = _declared(part, tail.pointer)
        narrow = _declared(part, tail.narrow)
        if not pointer or not narrow or narrow[0] not in ('s16', 'short'):
            return None
        for held in ('sel', 'idx'):
            if re.search(rf'\b{held}\b', clean[part.opening:part.end]):
                return None
        texts.append(_write_helper(WRITE, tail, pointer[0]))
        high, low = tail.high.strip(), tail.low.strip()
        rise = '-' + low.lstrip('-( ').rstrip(') ') if not low.startswith('(') else low
        guard = f'{tail.value} <= {high}'
        if flip:
            clamp = (f'    if ({tail.value} >= ({rise}))\n    {{\n      {tail.narrow} = {high};\n      if ({guard})\n      {{\n'
                     f'        {tail.narrow} = {tail.value};\n      }}\n    }}\n    else\n    {{\n      {tail.narrow} = {rise};\n    }}\n')
        else:
            clamp = (f'    if ({tail.value} < ({rise}))\n    {{\n      {tail.narrow} = {rise};\n    }}\n    else\n    {{\n'
                     f'      {tail.narrow} = {high};\n      if ({guard})\n      {{\n        {tail.narrow} = {tail.value};\n      }}\n    }}\n')
        block = (f'{{\n    u32 sel = {tail.select};\n    u32 idx = {tail.index};\n    s16 {tail.narrow};\n{clamp}'
                 f'    {WRITE}({tail.pointer}, sel, idx, {tail.narrow});\n  }}\n  {tail.ret}\n')
        edits.append((tail.first.start, tail.nodes[-1].end, block.rstrip('\n')))
        used.update({tail.narrow, tail.value})
        used.update(re.findall(IDENT, clean[tail.first.start:tail.nodes[-1].end]))
        edits.extend(_outer_declaration(part, tail.narrow))
    revised = edit(source, edits + [(find(source, name)[0], find(source, name)[0], '\n'.join(texts) + '\n')])
    if carrier:
        again = view(revised, name)
        extra = _carrier(again) if again else []
        if not extra:
            return None
        revised = _switch_tidy(edit(revised, extra))
    return _drop_orphans(revised, name, used)


def _outer_declaration(part, name):
    """The function-level `s16 name;` line, which the tail's own block declares again."""
    hit = re.search(rf'(?m)^[ \t]*(?:{IDENT}\s+)+{re.escape(name)}\s*;[ \t]*\n', part.clean[part.opening:part.end])
    return [(part.opening + hit.start(), part.opening + hit.end(), '')] if hit else []


def _drop_orphans(source, name, names):
    """Declarations of locals the rewrite left unused, removed."""
    part = view(source, name)
    if not part:
        return source
    body = part.clean[part.opening:part.end]
    edits = []
    for hit in re.finditer(rf'(?m)^[ \t]*(?:{IDENT}\s+)+\**({IDENT})\s*;[ \t]*\n', body):
        if hit[1] in names and len(re.findall(rf'\b{re.escape(hit[1])}\b', body)) == 1:
            edits.append((part.opening + hit.start(), part.opening + hit.end(), ''))
    return edit(source, edits)


def variants(source, name):
    out, seen = [], set()
    for write, carrier, flip, family in ((False, False, False, FAMILY), (True, False, False, FAMILY),
                                         (True, True, False, BUNDLE), (True, False, True, BUNDLE),
                                         (True, True, True, BUNDLE)):
        text = _build(source, name, write, carrier, flip)
        if text and text not in seen:
            seen.add(text)
            out.append((family, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
