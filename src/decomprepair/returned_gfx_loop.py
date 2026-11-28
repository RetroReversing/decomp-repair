"""A returned display-list cursor that a loop appends commands to, read back as one `gfx++` cursor.

`returned_gfx_cursor` handles a `Gfx *f(Gfx *gfx)` routine whose commands are all straight-line stores. When a loop
also appends commands, gcc's loop pass writes them through a second pointer of its own, and m2c reads the whole thing
back as pointer chains:

    temp = arg0 + 8;
    cursor = temp + 8;
    words = cursor - 4;                      /* the loop's reduced address */
    M2C_FIELD(arg0, s32 *, 0) = 0xE7000000;  ...
    loop_1:
        if (...) {
            words += 8;
            cursor += 8;
            M2C_FIELD(words, s32 *, -4) = word0;
            M2C_FIELD(words, s32 *, 0) = word1;
        }
        ...
    M2C_FIELD(cursor, s32 *, 0) = 0xE7000000;
    M2C_FIELD(cursor, s32 *, 4) = 0;
    return cursor + 8;

The game wrote every command as a macro on `gfx++`; gcc makes the second pointer itself. This writes the commands
before the loop, in the loop and after it as `{ RepairGfxWords *_g = gfx; gfx += 8; ... }` blocks on the parameter,
drops the chain locals and returns the parameter. An 82-instruction N64 dot-drawing display list (SN GCC 2.8.1
`-O2`) went from 5445 (the saved draft) to 405 with this and `loop_else_break`; `or_chain_order` and
`statement_slide` took it to 0.

It declines unless every use of the parameter, the chain locals and the loop's two pointers is accounted for: the
leading stores cover both words of every command up to the loop cursor's start, each run in a block steps both
pointers by the same multiple of eight and writes both words of every command it steps over, and the trailing stores
cover every command up to the returned address. Values must call nothing, since the macros put words in address order.

Children: `returned_gfx_loop` (the loop left as it was) and `returned_gfx_loop_else_break`, the same with
`loop_else_break` applied to every loop: with m2c's `goto` loop left alone the macros can score no better than the
draft, so a one-step-at-a-time search needs the two together.
"""
import re

from .csource import _blank, find
from .loop_else_break import ALL as LOOP_ALL
from .loop_else_break import variants as _loops
from .returned_gfx_cursor import PARAMETER, WORDS, _plain_fields, _unexpanded

FAMILY = 'returned_gfx_loop'
LOOP_FAMILY = 'returned_gfx_loop_else_break'
FAMILIES = (FAMILY, LOOP_FAMILY)
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0x[0-9A-Fa-f]+|\d+)'
POINTER = r'(?:void|u8|s8|char)[ \t]*\*'
CHAIN = re.compile(rf'[ \t]*(?P<name>{IDENT}) = (?P<base>{IDENT}) (?P<sign>[-+]) (?P<add>{NUMBER});[ \t]*')
STEP = re.compile(rf'[ \t]*(?P<name>{IDENT}) \+= (?P<add>{NUMBER});[ \t]*')
STORE = re.compile(rf'[ \t]*M2C_FIELD\((?P<name>{IDENT}), [\w ]+\*+, (?P<off>-?{NUMBER})\) = (?P<value>[^;]+);[ \t]*')
RETURN = re.compile(rf'[ \t]*return (?P<name>{IDENT}) \+ (?P<add>{NUMBER});[ \t]*')


def _calls(value):
    value = re.sub(r'\(\s*(?:[su](?:8|16|32)|int|unsigned|void)[ \t]*\**\s*\)', '', value)
    return bool(re.search(rf'\b(?!sizeof\b)(?!0[xX]){IDENT}\s*\(', value)) or '++' in value or '--' in value


def _commands(words, count):
    """The values of `count` commands from {byte offset: value}, in address order, or None when one is missing."""
    if sorted(words) != [4 * k for k in range(2 * count)] or any(_calls(v) for v in words.values()):
        return None
    return [(words[8 * k], words[8 * k + 4]) for k in range(count)]


def _blocks(commands, cursor, indent):
    out = []
    for first, second in commands:
        inner = indent + '    '
        out += [f'{indent}{{',
                f'{inner}RepairGfxWords *_g = (RepairGfxWords *){cursor};',
                f'{inner}{cursor} = (void *)((char *){cursor} + 8);',
                f'{inner}_g->w0 = {first};',
                f'{inner}_g->w1 = (unsigned int)({second});',
                f'{indent}}}']
    return out


def _setup(line, words, cursor):
    hit = CHAIN.fullmatch(line)
    return bool(hit) and hit['name'] == words and hit['base'] == cursor


def _pairs(lines):
    """{loop cursor: (words pointer, bias)} for the `words = cursor - k;` lines."""
    found = {}
    for line in lines:
        hit = CHAIN.fullmatch(line)
        if hit and hit['sign'] == '-':
            found[hit['base']] = (hit['name'], -int(hit['add'], 0))
    return found


def _rewrite(source, name, parameter):
    span = find(source, name)
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    text = source[opening:span[1]]
    lines = text.split('\n')
    pairs = _pairs(lines)
    for cursor, (words, bias) in pairs.items():
        child = _one(lines, parameter, cursor, words, bias)
        if child is None:
            continue
        prefix = source[:opening]
        start = prefix.rfind('\n', 0, span[0] + 1) + 1 if prefix[span[0]:].strip() else span[0]
        if 'RepairGfxWords;' not in prefix:
            prefix = prefix[:start] + WORDS + prefix[start:]
        return prefix + '\n'.join(child) + source[span[1]:]
    return None


def _one(lines, parameter, cursor, words, bias):
    depth, depths = 0, []
    for line in lines:
        depths.append(depth)
        depth += _blank(line).count('{') - _blank(line).count('}')
    # the chain of locals that holds the parameter plus a constant, up to the loop cursor
    offsets, drop = {parameter: 0}, set()
    for k, line in enumerate(lines):
        hit = CHAIN.fullmatch(line)
        if hit and depths[k] == 1 and hit['sign'] == '+' and hit['base'] in offsets and hit['name'] not in offsets:
            offsets[hit['name']] = offsets[hit['base']] + int(hit['add'], 0)
            drop.add(k)
    if cursor not in offsets or offsets[cursor] % 8 or not offsets[cursor]:
        return None
    start = offsets.pop(cursor)
    setup = [k for k, line in enumerate(lines) if _setup(line, words, cursor)]
    if len(setup) != 1:
        return None
    drop.add(setup[0])
    head, head_lines, tail, tail_lines, runs, run = {}, [], {}, [], [], []
    returned = None
    for k, line in enumerate(lines):
        store, step, back = STORE.fullmatch(line), STEP.fullmatch(line), RETURN.fullmatch(line)
        in_run = (step and step['name'] in (cursor, words)) or (store and store['name'] == words)
        if run and (not in_run or depths[k] != depths[run[0]]):
            runs.append(run)
            run = []
        if in_run:
            run.append(k)
        elif store and store['name'] in offsets and depths[k] == 1:
            at = offsets[store['name']] + int(store['off'], 0)
            if at in head or at >= start:
                return None
            head[at] = store['value']
            head_lines.append(k)
        elif store and store['name'] == cursor and depths[k] == 1:
            at = int(store['off'], 0)
            if at in tail:
                return None
            tail[at] = store['value']
            tail_lines.append(k)
        elif back and back['name'] == cursor:
            if returned is not None or depths[k] != 1:
                return None
            returned = k
    if run:
        runs.append(run)
    if not runs or returned is None or not head_lines or not tail_lines:
        return None
    # the leading stores form one run (nothing but chain lines between them), all before the loop
    first, last = head_lines[0], head_lines[-1]
    if any(lines[k].strip() and k not in drop and k not in head_lines for k in range(first, last + 1)):
        return None
    if last > runs[0][0] or tail_lines[0] < runs[-1][-1] or returned < tail_lines[-1]:
        return None
    heading = _commands(head, start // 8)
    size = int(RETURN.fullmatch(lines[returned])['add'], 0)
    trailing = _commands(tail, size // 8) if size % 8 == 0 else None
    if heading is None or trailing is None:
        return None
    replace = {}
    for group in runs:
        stepped, by_cursor, found = 0, 0, {}
        for k in group:
            step, store = STEP.fullmatch(lines[k]), STORE.fullmatch(lines[k])
            if step and step['name'] == words:
                stepped += int(step['add'], 0)
            elif step:
                by_cursor += int(step['add'], 0)
            else:
                at = bias + stepped + int(store['off'], 0)
                if at in found:
                    return None
                found[at] = store['value']
        if stepped != by_cursor or not stepped or stepped % 8:
            return None
        commands = _commands(found, stepped // 8)
        if commands is None:
            return None
        replace[group[0]] = _blocks(commands, parameter, re.match(r'[ \t]*', lines[group[0]])[0])
        drop.update(group[1:])
    replace[first] = _blocks(heading, parameter, re.match(r'[ \t]*', lines[first])[0])
    replace[tail_lines[0]] = _blocks(trailing, parameter, re.match(r'[ \t]*', lines[tail_lines[0]])[0])
    drop.update(head_lines[1:])
    drop.update(tail_lines[1:])
    replace[returned] = [f'{re.match(r"[ \t]*", lines[returned])[0]}return {parameter};']
    out = []
    for k, line in enumerate(lines):
        if k in replace:
            out += replace[k]
        elif k not in drop:
            out.append(line)
    gone = [n for n in offsets if n != parameter] + [cursor, words]
    body = '\n'.join(out)
    for local in gone:
        body = re.sub(rf'(?m)^[ \t]*{POINTER}[ \t]*{local};[ \t]*\n', '', body, count=1)
        if re.search(rf'(?<![\w.>]){local}\b', _blank(body)):
            return None
    # the parameter is only the cursor of the new blocks: any other use would see it advanced
    uses = len(re.findall(rf'(?<![\w.>]){parameter}\b', _blank(body)))
    commands = len(heading) + len(trailing) + sum(len(v) // 6 for k, v in replace.items()
                                                  if k not in (first, tail_lines[0], returned))
    if uses != 3 * commands + 1:
        return None
    return body.split('\n')


def variants(source, name, header=''):
    if not find(source, name):
        return []
    read = _plain_fields(source, name) or source
    for text in (read, _unexpanded(read, name)):
        if not text:
            continue
        span = find(text, name)
        clean = _blank(text)
        head = clean[clean.rfind(name, 0, clean.find('{', span[0], span[1])):clean.find('{', span[0], span[1])]
        for parameter in PARAMETER.finditer(head):
            child = _rewrite(text, name, parameter['name'])
            if not child:
                continue
            result = [(FAMILY, child)]
            result += [(LOOP_FAMILY, looped) for family, looped in _loops(child, name) if family == LOOP_ALL]
            if len(result) == 1:
                result += [(LOOP_FAMILY, looped) for _, looped in _loops(child, name)][:1]
            return result
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
