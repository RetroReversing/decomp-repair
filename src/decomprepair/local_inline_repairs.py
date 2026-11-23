"""Inline a once-assigned local at one of its uses, or all of them.

m2c names every intermediate (`off = (a & 0xFFFF) * 100;`) and reuses it. The original often wrote the
expression again at some uses, and the compiler's value reuse follows that: an agent matched a function by
replacing the temporary at just one of its reads. The expression must be pure (no calls, assignments,
increments or address-of) and none of its operands may change after the temporary is set.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'single_use_inline'
FAMILIES = (FAMILY,)
_TYPE = r'(?:register\s+)?(?:unsigned\s+(?:char|short|int)|[su](?:8|16|32)|int|short|char|f32)\s*\**'
_LITERAL = re.compile(r'-?(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\Z')
_PURE = re.compile(r'[\w\s()+\-*/%&|^~<>!.\[\]]+\Z')


def _plain(expression):
    """Arithmetic on names and numbers: no call, no assignment, no increment, no address-of."""
    # (the address of a game global is a constant; the address of a local is not)
    return bool(_PURE.match(expression)) and not re.search(r'\w\s*\(|\+\+|--|(?:^|[(+\-*/%&|^~<>!\[])\s*&(?!\s*D_[0-9A-Fa-f]+\b)|&(?=[A-Za-z_(])(?!D_[0-9A-Fa-f]+\b)', expression)


def _changed(name, text):
    """`name` is assigned, stepped or address-taken in `text` (writing through a pointer, `*name = x`, is not)."""
    return bool(re.search(rf'(?<![*\w]){name}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\b{name}\s*(?:\+\+|--)|(?:\+\+|--)\s*{name}\b|&\s*{name}\b', text))


def _assignments(clean, base, end):
    """(start, stop, local, expression) of `T local = e;` and of `local = e;` for a local declared earlier."""
    text = clean[base:end]
    for decl in re.finditer(rf'(?m)^[ \t]*{_TYPE}\s*(\w+)\s*=\s*([^;{{}}]+);', text):
        yield base + decl.start(), base + decl.end(), decl[1], base + decl.start(2), base + decl.end(2)
    for decl in re.finditer(rf'(?m)^[ \t]*{_TYPE}\s*(\w+)\s*;', text):
        # m2c puts one statement on a line; an edited source may not (`c2 = 2; do { f(); } while (0);`)
        later = re.search(rf'(?m)(?:^[ \t]*|(?<=;)[ \t]+){decl[1]}\s*=\s*([^;{{}}=][^;{{}}]*);', text[decl.end():])
        if later:
            first = decl.end() + later.start()
            yield base + first, base + decl.end() + later.end(), decl[1], base + decl.end() + later.start(1), base + decl.end() + later.end(1)


def _adjacent(source, part):
    """`x = E;` followed at once by the only statement that reads `x`: E (calls allowed) moves into it.

    The reading statement may only store: another call or step in it could swap order with E."""
    clean, base, result = part.clean, part.opening + 1, []
    # (the assignment may follow another statement on its line: `S; x = E;`, which edited sources and m2c's own
    # `a = b; c = d;` lines have, and the line-start-only form skipped)
    for decl in re.finditer(r'(?m)((?:^[ \t]*|(?<=;)[ \t]+))(\w+)\s*=\s*([^;{}=][^;{}]*);[ \t]*\n([ \t]*[^;{}\n]+;)', clean[base:part.end]):
        local, nxt = decl[2], decl[4]
        if not re.search(rf'^\s*[*\w\[\]().+\- >]*=\s*(?:\([^()]*\)\s*)?{local}\s*;$', nxt) or re.search(r'\w\s*\(\s*[^)]*\)\s*[^;]*\b' + local, nxt.split('=', 1)[0]):
            continue
        rest = clean[base + decl.end():part.end]
        if re.search(rf'\b{local}\b', rest) or len(re.findall(rf'\b{local}\b', nxt)) != 1:
            continue
        if re.search(r'\w\s*\(\s*[^)]*\)\s*\(|\+\+|--', nxt) or re.search(r'\b\w+\s*\(', nxt.replace('(u8 *)', '').replace('(u32)', '')):
            continue
        expression = source[base + decl.start(3):base + decl.end(3)].strip()
        use = base + decl.start(4) + nxt.index(local, nxt.index('='))
        start, end = base + decl.start(), base + decl.end(3) + 1
        # drop the assignment (its line), then put E in the use; the declaration of `x` stays unused
        mid_line = start > 0 and source[start - 1] != '\n'
        text = edit(source, [(use, use + len(local), '(' + expression + ')'),
                             (start, source.index('\n', end) + (0 if mid_line else 1), '')])
        result.append((FAMILY, text))
    return result


def _block_end(clean, base, start, end):
    """Where the block holding `start` closes: the function's end at top level, else its own `}` (None if unbalanced)."""
    depth = clean[base:start].count('{') - clean[base:start].count('}')
    if depth == 0:
        return end
    if depth < 0:
        return None
    level = 0
    for index in range(start, end):
        if clean[index] == '{':
            level += 1
        elif clean[index] == '}':
            level -= 1
            if level < 0:
                return index
    return None


def variants(source, name, limit=8):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = _adjacent(source, part)
    for start, end, local, first, last in _assignments(clean, part.opening + 1, part.end):
        expression = source[first:last].strip()
        if not _plain(expression):
            continue
        # A local declared in an inner block (m2c's `u32 high = (u32)(arg1 & 0xffff) >> 7;` before a loop) is read
        # only up to that block's close. A voice-list walk matched once both such locals were written at their call
        # sites again (a neutral step, 623 -> 623) and the scaled index was staged (-> 0).
        block_end = _block_end(clean, part.opening + 1, start, part.end)
        if block_end is None:
            continue
        body = clean[end:block_end]
        if _changed(local, body) or any(_changed(o, body) for o in set(re.findall(r'[A-Za-z_]\w*', expression))):
            continue
        uses = [end + h.start() for h in re.finditer(rf'\b{local}\b', body)]
        # A constant read once is still worth spelling out: a literal store in a loop is a movable loop.c hoists
        # and the scheduler floats up to the previous barrier, a constant local is fixed where it was set (an N64 init
        # function whose loop stored 2, 100 and 1 matched only with the literals).
        if len(uses) < (1 if _LITERAL.match(expression) else 2):
            continue

        def spelled(position, expression=expression, local=local):
            if re.fullmatch(r'\w+', expression):
                return expression
            before, after = clean[:position].rstrip()[-1:], clean[position + len(local):].lstrip()[:1]
            return expression if before == '[' and after == ']' else '(' + expression + ')'

        edits = [[(u, u + len(local), spelled(u))] for u in uses]
        for group in edits + ([[e for g in edits for e in g]] if len(uses) > 1 else []):
            result.append((FAMILY, edit(source, group)))
        if len(result) >= limit:
            break
    return result[:limit]


_RECORD_COPY = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<local>[A-Za-z_]\w*)\s*=\s*(?P<address>[^;{}\n]+);[ \t]*\n'
    r'[ \t]*\*\s*\(\s*\(\s*(?P<record>[A-Za-z_]\w*)\s*\*\s*\)\s*(?P<array>[A-Za-z_]\w*)\s*\)'
    r'\s*=\s*\*\s*\(\s*\(\s*(?P=record)\s*\*\s*\)\s*(?P=local)\s*\)\s*;')
_WORD_READ = re.compile(r'lw (\$\w+), (?:(0x[0-9a-f]+|[0-9]+))?\((\$\w+)\)')


def _indexed_copy_registers(rows):
    for i, (_, target, current) in enumerate(rows[:-3]):
        left, right = _WORD_READ.fullmatch(target), _WORD_READ.fullmatch(current)
        if not left or not right or int(left[2] or '0', 0) or int(right[2] or '0', 0):
            continue
        # The address and first data word exchange registers while the destination stays put.
        if left[1] == left[3] or (left[1], left[3]) != (right[3], right[1]):
            continue
        following = [(_WORD_READ.fullmatch(a), _WORD_READ.fullmatch(b)) for _, a, b in rows[i + 1:i + 3]]
        if not all(a and b and a[1] == b[1] and int(a[2] or '0', 0) == int(b[2] or '0', 0) == step
                   and a[3] == left[3] and b[3] == right[3] for step, (a, b) in zip((4, 8), following)):
            continue
        _, store, old_store = rows[i + 3]
        if (store.startswith(f'sw {left[1]}, ') and store.endswith('($sp)')
                and old_store == store.replace(f'sw {left[1]}, ', f'sw {right[1]}, ', 1)):
            return True
    return False


def measured_record_copy_inline(source, name, rows, header=''):
    """Inline the sole address use when the measured three-word copy swaps its registers."""
    if not _indexed_copy_registers(rows):
        return []

    from .csource import _blank
    from .frame_padding_repairs import declaration_ends

    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm|__asm__)\b', part.body):
        return []
    declarations = {}
    begin = part.opening + 1
    for end in declaration_ends(part):
        decl = re.fullmatch(r'\s*(?:void\s*\*\s*([A-Za-z_]\w*)|f32\s+([A-Za-z_]\w*)\s*\[\s*3\s*\])\s*;',
                            part.clean[begin:end])
        if decl:
            declarations[decl[1] or decl[2]] = 'pointer' if decl[1] else 'array'
        begin = end

    macro_text = (_blank(header) + '\n' + part.clean).replace('\\\n', ' ')
    macros = re.findall(r'(?m)^[ \t]*#\s*(?:define|undef)\s+([^\n]+)', macro_text)
    out = []
    for hit in _RECORD_COPY.finditer(part.clean, part.opening + 1, part.end):
        local, array, record = (hit[k] for k in ('local', 'array', 'record'))
        if declarations.get(local) != 'pointer' or declarations.get(array) != 'array':
            continue
        if part.clean[part.opening + 1:hit.start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        if not re.search(r'\+.*\*|\*.*\+', hit['address']):
            continue
        if len(re.findall(rf'\b{local}\b', part.body)) != 3:
            continue
        shadow = rf'\b[A-Za-z_]\w*(?:\s+\**\s*|\s*\*+\s*){array}\s*(?=[;=,\[])'
        if len(re.findall(shadow, part.body)) != 1:
            continue
        if any({local, array, record, 'f32'} & set(re.findall(r'[A-Za-z_]\w*', macro)) for macro in macros):
            continue
        if hit[0] != source[hit.start():hit.end()]:
            continue
        replacement = f"{hit['indent']}*(({record} *) {array}) = *(({record} *) (void *)({hit['address']}));"
        out.append((FAMILY, edit(source, [(hit.start(), hit.end(), replacement)])))
    return out[:3]
