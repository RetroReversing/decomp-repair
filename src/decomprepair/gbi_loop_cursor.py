"""A display-list cursor read from a pointer parameter, written through a second pointer the loop pass kept apart.

A builder that takes the address of the caller's cursor (`Gfx **`, `s32 *arg0` in the draft) copies it once, writes
its commands with the SDK's macros on `gfx++`, and stores the cursor back at the end. gcc 2.7.2's loop pass turns that
one pointer into two when the writes sit in a loop: the cursor itself, advanced by a constant per arm (`+= 0x38`
after seven commands, `+= 0x18` after three), and a reduced address `base` set to `cursor - 4` before the loop and
stepped by 8 for every command, each word stored at `base - 4` / `base + 0` after the step. m2c reads that back as two
pointer chains, `temp = var_t0 + 8; M2C_FIELD(temp, s32 *, -4) = word0; M2C_FIELD(prev, s32 *, 8) = word1;` for
each command and `var_t1_2 = var_t1 + 0x38;` per arm. gbi_macro_commands only reads a cursor that is a global, so a
draft like this had no way back to the macros: the words stayed raw stores through two pointers and the searches
around them stalled however the arithmetic was spelled (340 attempts, saved best 10891).

On a 369-instruction N64 sprite-tile builder (KMC gcc 2.7.2: a loop over tiles, each tile a seven-command texture load
in one of two arms and a three-command texture rectangle in one of two more) writing the commands as the SDK macros
on one cursor was the step that gave the loop pass its own pointers back: 11160 -> 7705 -> 1565 once the texture
rectangle was whole in each arm and its operands were locals, byte-identical after four more small steps. The macro
form is the original's, and gcc turns it into the reduced base and the chunked cursor increments by itself.

This family finds the pointer chains: the cursor local `X = *P;` and its store back `*P = X;` (P a parameter, or a
local copy of one), a loop base `B = X - 4;` whose commands step by eight, the increments of the cursor per iteration
(they must add up to the steps of the base, so `B == X - 4` at the top of every iteration and the rewrite writes the
same words at the same addresses), and every store through the chain. A store's address is the chain's constant offset
plus its own, which names a command and one of its two words. Every command must be written on every path through
an iteration: the commands that are in the loop body itself, or in the two arms of one `if`/`else` that between them
cover the others, one after the other with no gap. A block that holds consecutive commands gets one macro per
command at the place of its last store (`gDPSetTile(gfx++, ...)`), the words decoded against the SDK's own encodings
by gbi_macro_commands. Words are read through the locals they were computed into (`temp_t7 = (arg2 & 7) << 0x15;` is
the format field, so the macro takes `arg2`), and a float that m2c converted with `(s32)` keeps its conversion (the
macro's own cast of a float would be an unsigned conversion). A texture rectangle that m2c split over an `if`/`else`
and the join after it is written whole in each arm, as the game wrote it and cross-jumping merged it again. The cursor
is a local `Gfx *gfx` and the parameter becomes `Gfx **`. Nothing is rewritten when an address does not land on a
command's word, a store sits outside a block that can be given commands, or a name the rewrite removed is still read
afterwards: the judge never sees a draft this family could not account for word by word.

The second child, `gbi_loop_cursor_invariants`, is the first with `hoisted_invariant_inline` applied to all the loop
invariants m2c named (`temp_s1 = arg12 - 1;`, `sp14 = (u32) arg4 >> 1;`): in the 369-instruction function the macros alone
stood at 16710 and the invariants written back at 13135, and a chain that starts from the first only finds the invariants
one at a time, none of which moves the score alone.
"""
import re

from .csource import find
from .display_cursor_record_repairs import _statements
from .gbi_macro_commands import _macros, _masked, _ors, _prelude, _strip, _whole_line
from .hoisted_invariant_inline import variants as _invariants
from .integer_repair_support import IDENT, edit, view

FAMILY = 'gbi_loop_cursor'
INVARIANT_FAMILY = 'gbi_loop_cursor_invariants'
FAMILIES = (FAMILY, INVARIANT_FAMILY)
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
LOCAL = 'gfx'
MARK = '__f2i'

STORE = re.compile(rf'M2C_FIELD\s*\(\s*(?P<p>{IDENT})\s*,\s*(?:s32|u32)\s*\*\s*,\s*(?P<off>-?\s*(?:{NUMBER}))\s*\)\s*=(?!=)\s*(?P<v>[^;]+?)\s*;\Z')
CHAIN = re.compile(rf'(?P<a>{IDENT})\s*=\s*(?P<b>{IDENT})\s*(?:(?P<sign>[-+])\s*(?P<k>{NUMBER}))?\s*;\Z')
READ = re.compile(rf'(?P<x>{IDENT})\s*=\s*\*\s*(?P<p>{IDENT})\s*;\Z')
WRITE = re.compile(rf'\*\s*(?P<p>{IDENT})\s*=(?!=)\s*(?P<x>{IDENT})\s*;\Z')
ALIAS = re.compile(rf'(?P<a>{IDENT})\s*=\s*(?P<b>{IDENT})\s*;\Z')
DECLARATION = re.compile(rf'(?:{IDENT}\s+)+\**\s*(?P<n>{IDENT})\s*;\Z')
PLAIN = re.compile(rf'(?P<n>{IDENT})\s*=(?!=)\s*(?P<v>[^;]+);\Z')
CALL = re.compile(rf'\b(?!(?:if|while|sizeof)\b){IDENT}\s*\(')
FLOATING = re.compile(rf'\b(?:f32|f64|float|double)\s+(?P<n>{IDENT})\s*[;,)]')
INTEGER_CAST = r'\(\s*(?:s32|u32|int|unsigned(?:\s+int)?|long)\s*\)\s*'


def _num(text):
    return int(text.replace(' ', ''), 0)


def _pure(value):
    return not CALL.search(value) and '++' not in value and '--' not in value and '=' not in value.replace('==', '')


def _blocks(clean, start, end):
    """(owner, parent, close): for each offset the `{` of the innermost block that holds it (start - 1 for the body),
    each block's parent block, and each block's closing brace."""
    owner, parent, close, stack = {}, {}, {}, [start - 1]
    for i in range(start, end):
        if clean[i] == '{':
            parent[i] = stack[-1]
            stack.append(i)
        elif clean[i] == '}' and len(stack) > 1:
            close[stack.pop()] = i
        owner[i] = stack[-1]
    return owner, parent, close


def _offsets(chain, root):
    """{name: byte offset from root} over `A = B + k` links, or None when one name gets two different offsets."""
    known = {root: 0}
    for _ in range(len(chain) + 1):
        changed = False
        for a, b, k in chain:
            if a == root or b not in known:
                continue
            if a in known:
                if known[a] != known[b] + k:
                    return None
                continue
            known[a] = known[b] + k
            changed = True
        if not changed:
            break
    return known


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    start, end = part.opening + 1, part.end - 1
    if re.search(r'\b(?:for|while)\s*\([^)]*;|\bvolatile\b|\basm\b|\bgoto\b', clean[part.opening:part.end]):
        return []
    spans = _statements(clean, start, end)
    text = [clean[a:b] for a, b in spans]
    owner, parents, closes = _blocks(clean, start, end)
    found = _facts(clean, part, name, text)
    if found is None:
        return []
    blocks = {}
    for index, command, word, value in found['placed']:
        blocks.setdefault(owner[spans[index][0]], {}).setdefault(command, {})[word] = (index, value)
    for commands in blocks.values():
        ordered = sorted(commands)
        if ordered != list(range(ordered[0], ordered[-1] + 1)) or any(set(w) != {0, 1} for w in commands.values()):
            return []
    joins = _joins(clean, spans, parents, closes, blocks)
    if joins is None or not _covered(clean, spans, owner, closes, blocks, found):
        return []
    return _emit(source, name, header, part, spans, text, owner, closes, blocks, joins, found)


def _facts(clean, part, name, text):
    """The cursor, the two chains and each store's (statement, command, word, value), or None."""
    params = re.search(rf'\b{re.escape(name)}\s*\((?P<p>[^)]*)\)', clean[:part.opening + 1])
    if not params:
        return None
    parameters = {m['n'] for m in re.finditer(rf'[^,]*?\*\s*(?P<n>{IDENT})\s*(?:,|\Z)', params['p'])}
    reads = [(i, READ.match(t)) for i, t in enumerate(text) if READ.match(t)]
    writes = [(i, WRITE.match(t)) for i, t in enumerate(text) if WRITE.match(t)]
    if len(reads) != 1 or len(writes) != 1:
        return None
    (read_at, read), (write_at, write) = reads[0], writes[0]
    alias = {m['a']: m['b'] for t in text if (m := ALIAS.match(t)) and m['b'] in parameters}
    pointer = alias.get(read['p'], read['p'])
    cursor = read['x']
    if pointer not in parameters or alias.get(write['p'], write['p']) != pointer or write['x'] != cursor:
        return None
    chain = [(m['a'], m['b'], (-1 if m['sign'] == '-' else 1) * (_num(m['k']) if m['k'] else 0))
             for t in text if (m := CHAIN.match(t)) and m['a'] != m['b'] and not READ.match(t)]
    stores = [(i, m['p'], _num(m['off']), m['v'].strip()) for i, t in enumerate(text) if (m := STORE.match(t))]
    if len(stores) < 4:
        return None
    root = stores[0][1]
    known = _offsets(chain, root)
    if known is None or any(p not in known for _, p, _, _ in stores):
        return None
    # the loop base is set from the cursor (B = X - 4) and both advance by the same amount per iteration
    setups = sorted({(a, b, k) for a, b, k in chain if a == root and b not in known})
    advance = sorted({(a, b, k) for a, b, k in chain if a == root and b in known})
    if len(setups) != 1 or len(advance) != 1 or (setups[0][2] + 4) % 8:
        return None
    parent = setups[0][1]
    step_root = known[advance[0][1]] + advance[0][2]
    walk = _offsets([c for c in chain if c[0] != root], parent)
    back = sorted({(a, b, k) for a, b, k in chain if a == parent and b in walk}) if walk is not None else []
    if len(back) != 1 or walk[back[0][1]] + back[0][2] != step_root or step_root % 8 or step_root <= 0:
        return None
    moved_at = min(i for i, t in enumerate(text) if (m := CHAIN.match(t)) and m['a'] == root and m['b'] in known)
    placed = []
    for index, pointer_name, off, value in stores:
        base = step_root if pointer_name == root and index > moved_at else known[pointer_name]
        rel = base + off - 4
        if rel % 4 or rel < 0 or rel // 8 >= step_root // 8:
            return None
        placed.append((index, rel // 8, rel % 8 // 4, value))
    return {'placed': placed, 'cursor': cursor, 'pointer': pointer, 'alias': set(alias), 'read_at': read_at,
            'write_at': write_at, 'names': set(known) | set(walk) | {cursor, parent, root},
            'count': step_root // 8, 'advance_at': moved_at}


def _joins(clean, spans, parents, closes, blocks):
    """{join block: [its two arms]}: the block that holds the statements after an `if`/`else` whose arms each end one
    command before the join's first. None when such a pair is not exactly an if/else followed by the join."""
    joins = {}
    for block, commands in blocks.items():
        up = parents.get(block)
        if up in blocks and min(blocks[up]) == max(commands) + 1 and \
                all(spans[i][0] > closes[block] for words in blocks[up].values() for i, _ in words.values()):
            joins.setdefault(up, []).append(block)
    for join, arms in joins.items():
        arms.sort()
        first = min(spans[i][0] for words in blocks[join].values() for i, _ in words.values())
        if len(arms) != 2 or any(max(blocks[a]) != min(blocks[join]) - 1 for a in arms) \
                or clean[closes[arms[0]] + 1:arms[1]].strip() != 'else' or clean[closes[arms[1]] + 1:first].strip():
            return None
    return joins


def _covered(clean, spans, owner, closes, blocks, found):
    """Every command is written on every path through an iteration, once: the blocks with the same commands are the
    two arms of one if/else, a lone block is the loop body itself, and the ranges follow one another from command 0."""
    loop = owner[spans[found['advance_at']][0]]
    groups = {}
    for block, commands in blocks.items():
        groups.setdefault((min(commands), max(commands)), []).append(block)
    expect = 0
    for (first, last), group in sorted(groups.items()):
        if first != expect:
            return False
        group.sort()
        if len(group) == 2:
            if clean[closes[group[0]] + 1:group[1]].strip() != 'else':
                return False
        elif len(group) != 1 or group[0] != loop:
            return False
        expect = last + 1
    return expect == found['count']


def _emit(source, name, header, part, spans, text, owner, closes, blocks, joins, found):
    clean = part.clean
    start, end = part.opening + 1, part.end - 1
    masked = _masked(clean[start:end])
    pointer, names = found['pointer'], found['names']
    floats = {m['n'] for m in FLOATING.finditer(clean[:end])}
    arm_of = {a: j for j, arms in joins.items() for a in arms}
    assigns = {}
    for i, t in enumerate(text):
        if (m := PLAIN.match(t)) and not DECLARATION.match(t):
            assigns.setdefault(m['n'], []).append((i, m['v'].strip()))

    def definition(ident, block, position):
        """The value of a local assigned once on the way to `position`: in its own block, else the only one."""
        if ident in names:
            return None
        here = [(i, v) for i, v in assigns.get(ident, []) if owner[spans[i][0]] == block and spans[i][1] <= position]
        seen = here or [(i, v) for i, v in assigns.get(ident, []) if spans[i][1] <= position]
        if len(seen) != 1 or (not here and len(assigns[ident]) != 1) or not _pure(seen[0][1]):
            return None
        i, value = seen[0]
        for other in set(re.findall(IDENT, value)):
            if any(spans[i][1] <= spans[j][0] < position for j, _ in assigns.get(other, [])):
                return None
        return value

    def words_of(commands, block, position):
        out = []
        for command in sorted(commands):
            row = []
            for word in (0, 1):
                value = commands[command][word][1]
                for f in floats:
                    value = re.sub(rf'{INTEGER_CAST}(?<![\w.>]){f}\b', f'{MARK}({f})', value)
                for _ in range(8):
                    parts, changed = _ors(value), False
                    for k, piece in enumerate(parts):
                        ident = _strip(piece)
                        if re.fullmatch(IDENT, ident) and (inner := definition(ident, block, position)) is not None:
                            parts[k] = f'({inner})'
                            changed = True
                    value = ' | '.join(parts)
                    if not changed:
                        break
                row.append(value)
            out.append(tuple(row))
        return out

    local = next(n for n in (LOCAL, 'gdl', 'dl', '_gfx') if not re.search(rf'\b{n}\b', clean))
    edits, used, delete = [], set(), set()
    for block, commands in blocks.items():
        member = sorted(i for words in commands.values() for i, _ in words.values())
        delete.update(member)
        if block in joins:
            continue
        if block in arm_of:
            sequence = words_of(commands, block, closes[block]) + words_of(blocks[arm_of[block]], block, closes[block])
            site = closes[block]
        else:
            sequence = words_of(commands, block, 1 << 30)
            site = None
        macros = [(m, [re.sub(rf'{MARK}\((\w+)\)', r'(s32) \1', a) for a in args]) for m, args in _macros(sequence, masked)]
        used.update(m for m, _ in macros)
        lines = [f'{m}({", ".join([local + "++"] + [_simple(a) for a in args])});' for m, args in macros]
        first_line = clean.rfind('\n', 0, spans[member[0]][0]) + 1
        indent = re.match(r'[ \t]*', clean[first_line:])[0]
        body = f'\n{indent}'.join(lines)
        if site is None:
            edits.append((spans[member[-1]], member[-1], body))
        else:
            line = clean.rfind('\n', 0, site) + 1
            if clean[line:site].strip():
                edits.append(((site, site), None, ' ' + body + ' '))
            else:
                edits.append(((line, line), None, f'{indent}{body}\n'))
    for i, t in enumerate(text):
        if (m := PLAIN.match(t)) and m['n'] in names and i not in (found['read_at'], found['write_at']):
            delete.add(i)
        elif (m := DECLARATION.match(t)) and m['n'] in names:
            delete.add(i)
    plan = []
    for (a, b), keep, body in edits:
        if keep is not None:
            delete.discard(keep)
        plan.append((a, b, body))
    for i in sorted(delete):
        plan.append((*_whole_line(source, *spans[i]), ''))
    a, b = spans[found['read_at']]
    plan.append((a, b, f'{local} = (Gfx *) *{pointer};'))
    a, b = spans[found['write_at']]
    plan.append((a, b, f'*{pointer} = {local};'))
    signature = re.search(rf'\b{re.escape(name)}\s*\((?P<p>[^)]*)\)', clean[:part.opening + 1])
    argument = re.search(rf'(?:\b\w+\s+)*\*\s*\b{re.escape(pointer)}\b', signature['p'])
    if not argument:
        return []
    plan.append((signature.start('p') + argument.start(), signature.start('p') + argument.end(), f'Gfx **{pointer}'))
    plan.append((part.opening + 1, part.opening + 1, f'\n    Gfx *{local};'))
    begin = find(source, name)[0]
    prelude = _prelude(sorted(used), header, clean[:part.opening])
    if not re.search(r'\bwords\b', header + clean[:part.opening]) and re.search(r'\bGfx\b', header + clean[:part.opening]):
        prelude = prelude.replace('->words.', '->')
    plan.append((begin, begin, prelude))
    out = _tidy(edit(source, plan), name, names | found['alias'])
    if not out:
        return []
    # the loop invariants m2c named (temp_s1, sp14) are the other half of the same draft: written at their uses they
    # take the loop's pointers and registers back to the original's, which neither half does alone (16710 -> 13135)
    both = _invariants(out, name, header)
    return [(FAMILY, out)] + ([(INVARIANT_FAMILY, both[0][1])] if both else [])


def _simple(arg):
    """`(e - 1) + 1` (the width a SETIMG word stored and the macro adds one to) is `e`."""
    m = re.fullmatch(r'\((.+) - 1\) \+ 1', arg)
    return m[1] if m and m[1].count('(') == m[1].count(')') else arg


def _tidy(source, name, gone):
    """Delete the assignments and declarations nothing reads any more; None when a name the rewrite removed is still
    used."""
    for _ in range(60):
        part = view(source, name)
        if not part:
            return None
        clean = part.clean
        spans = _statements(clean, part.opening + 1, part.end - 1)
        body = clean[part.opening + 1:part.end - 1]
        count = {n: len(re.findall(rf'(?<![\w.>]){re.escape(n)}\b', body)) for n in set(re.findall(IDENT, body))}
        writes, declared = {}, {}
        for a, b in spans:
            if m := DECLARATION.fullmatch(clean[a:b]):
                declared[m['n']] = declared.get(m['n'], 0) + 1
            elif m := PLAIN.match(clean[a:b]):
                writes[m['n']] = writes.get(m['n'], 0) + 1
        dead = None
        for a, b in spans:
            t = clean[a:b]
            if (m := PLAIN.match(t)) and not DECLARATION.match(t) and _pure(m['v']) and m['n'] != LOCAL \
                    and count[m['n']] == writes[m['n']] + declared.get(m['n'], 0):
                dead = (a, b)
                break
            if (m := DECLARATION.fullmatch(t)) and count.get(m['n'], 0) == 1:
                dead = (a, b)
                break
        if dead is None:
            break
        source = edit(source, [(*_whole_line(source, *dead), '')])
    part = view(source, name)
    if not part:
        return None
    body = part.clean[part.opening + 1:part.end - 1]
    if any(re.search(rf'(?<![\w.>]){re.escape(n)}\b', body) for n in gone):
        return None
    return source


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
