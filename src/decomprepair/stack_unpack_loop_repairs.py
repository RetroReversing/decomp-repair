"""m2c's pointer-walk unpacker, written back as the indexed loop over stack arrays it came from.

A function that unpacks a bit-packed record (a header, then N equal records) into small arrays on its stack, then
hands the arrays to a callee, comes out of m2c like this: one scalar per stack slot named by its offset (`s32 spB0;`,
`s16 spD0; s16 spD2; ...`), a labelled block that steps one cursor per array by that array's stride and a source
cursor by the record size, and a call whose stack arguments it never saw:

    var_v1 = &sp48;  var_a3 = &spC8;  var_v0 = arg1;
    rows: { var_v1 += 0x1A; var_a3 += 2; *(s16 *)((char *)(var_a3) + -2) = ...u8 at var_v0 + 5...; var_v0 += 7; ... }
    if (var_v1 != &spB0) goto rows;

IDO unrolls and schedules the indexed form `a[i] = ...; e[i*13+k] = ...; p[i*7+5+k]` exactly as the game's code does,
and the cursor form never: the index is what lets it keep the stride updates where the target has them. The rewrite
needs facts the draft lacks, so they come from its own names and the target: a stack object's name is its offset, so
an object runs to the next object's offset (the arrays), the loop's end test gives the count, each cursor's stride is
its own step, and the target's stores to the argument slots say which objects the call takes.

An N64 audio-header unpacker built with IDO sat at score 11,654 under GCC-shaped drafts and matched exactly once its
loop was this indexed form over `s16 h[8]`, `a[4]`, `c[4]`, `b[4]`, `d[4]`, `e[52]` (declared highest offset first).

Offered only when the meaning is unchanged: the end test compares a stepping cursor with the address of a stack object
a whole number of strides past its start, every access through a cursor is a plain load or store at a constant offset
(its address never escapes), the walked objects are used only by address or through the walk, and every stack object
the loop touches is an array of its stores' width.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stack_unpack_loop'
FAMILIES = (FAMILY,)

SIZES = {'s8': 1, 'u8': 1, 'char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2, 'unsigned short': 2, 's32': 4,
         'u32': 4, 'int': 4, 'unsigned int': 4, 'unsigned long': 4, 'long': 4}
NUM = r'-?(?:0[xX][0-9a-fA-F]+|\d+)'
ID = r'[A-Za-z_]\w*'
DECL = re.compile(r'(?m)^[ \t]*(?:register[ \t]+)?([A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)?)[ \t]+(sp([0-9A-F]+))[ \t]*;[ \t]*\n')


def _int(text):
    return int(text, 0)


def _frame(asm):
    m = re.search(r'addiu\s+\$sp\s*,\s*\$sp\s*,\s*-(0x[0-9a-fA-F]+|\d+)', asm or '')
    return int(m[1], 0) if m else None


def call_arguments(asm, params):
    """The stack arguments of the function's one call, as C expressions (`&sp48`, a parameter name), from the target:
    `sw reg, 0x10+4k($sp)` where reg was set by `addiu reg, $sp, N` or loaded from a parameter's home slot."""
    frame = _frame(asm)
    if frame is None:
        return None
    lines = [re.sub(r'/\*.*?\*/', '', line).strip() for line in (asm or '').splitlines()]
    out = {}
    value = {}
    called = False
    for line in lines:
        m = re.match(r'addiu\s+(\$\w+)\s*,\s*\$sp\s*,\s*(0x[0-9a-fA-F]+|\d+)$', line)
        if m:
            value[m[1]] = f'&sp{int(m[2], 0):X}'
        m = re.match(r'lw\s+(\$\w+)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)$', line)
        if m:
            slot = int(m[2], 0) - frame
            value[m[1]] = params[slot // 4] if slot % 4 == 0 and 0 <= slot // 4 < len(params) else None
        m = re.match(r'sw\s+(\$\w+)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)$', line)
        if m and 0x10 <= int(m[2], 0) < 0x30 and value.get(m[1]):
            out[(int(m[2], 0) - 0x10) // 4 + 4] = value[m[1]]
        if re.match(r'jal\b', line):
            called = True
        elif called:
            break  # (the delay slot's own store is the last one that counts)
    return [out[k] for k in sorted(out)] if out and sorted(out) == list(range(4, 4 + len(out))) else None


def _objects(heads, last_end):
    """(offset -> extent in bytes): an object runs to the next head, the last one to the end of its scalar run."""
    ordered = sorted(heads)
    return {off: (ordered[i + 1] if i + 1 < len(ordered) else last_end) - off for i, off in enumerate(ordered)}


def _swap_or(statement):
    """`x = (cast)((A) | (B));` with A and B swapped: the operand IDO evaluates first is the one written first."""
    depth, best = 0, None
    for k, ch in enumerate(statement):
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif ch == '|' and statement[k - 1:k + 1] != '||' and statement[k:k + 2] != '||' and statement.find('=') < k:
            if best is None or depth < best[0]:
                best = (depth, k)
    if best is None:
        return statement
    k = best[1]
    # the operands run from the enclosing opening bracket (or the `=`) to the closing one (or the `;`)
    equals = statement.find('=')
    left, level = k, 0
    while left > equals:
        left -= 1
        if left == equals:
            break
        if statement[left] in ')]':
            level += 1
        elif statement[left] in '([':
            if level == 0:
                break
            level -= 1
    right, level = k, 0
    while right < len(statement) - 1:
        right += 1
        if statement[right] in '([':
            level += 1
        elif statement[right] in ')]' :
            if level == 0:
                break
            level -= 1
        elif statement[right] == ';' and level == 0:
            break
    a, b = statement[left + 1:k].strip(), statement[k + 1:right].strip()
    if not a or not b:
        return statement
    return statement[:left + 1] + b + ' | ' + a + statement[right:]


def _inline_temps(lines, scalars):
    """Fold a temporary assigned once and read once in the loop into its reader (m2c's `temp_t4 = *(u8 *)...;`)."""
    lines = list(lines)
    for name in scalars:
        sets = [n for n, l in enumerate(lines) if re.match(rf'\s*{re.escape(name)}\s*=[^=]', l)]
        uses = [n for n, l in enumerate(lines) if re.search(rf'\b{re.escape(name)}\b', l) and n not in sets]
        if len(sets) != 1 or len(uses) != 1 or uses[0] < sets[0]:
            continue
        value = re.match(rf'\s*{re.escape(name)}\s*=\s*(.*?);\s*$', lines[sets[0]])
        if not value or re.search(r'[=;]', value[1]):
            continue
        lines[uses[0]] = re.sub(rf'\b{re.escape(name)}\b', lambda m, v=value[1]: '(' + v + ')', lines[uses[0]])
        lines[sets[0]] = ''
    return [l for l in lines if l.strip()]


def _sorted_runs(lines):
    """Stores to one array's consecutive elements in ascending index order (m2c lists them in the compiler's order)."""
    key = re.compile(r'^\s*\(?\s*(sp[0-9A-F]+)\[i(?:\*\d+)?(?:\+(\d+))?\]')
    out, run = [], []
    def flush():
        out.extend(sorted(run, key=lambda l: int(key.match(l)[2] or 0)) if len({key.match(l)[1] for l in run}) == 1 else run)
        run.clear()
    for line in lines:
        m = key.match(line)
        if m and (not run or key.match(run[-1])[1] == m[1]):
            run.append(line)
        else:
            flush()
            if m:
                run.append(line)
            else:
                out.append(line)
    flush()
    return out


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature = re.search(r'\b' + re.escape(name) + r'\s*\(([^()]*)\)\s*$', clean[span[0]:opening])
    if not signature:
        return []
    params = [(re.sub(r'\s+', ' ', p).strip()) for p in signature[1].split(',') if p.strip()]
    names = [m[1] if (m := re.search(rf'({ID})\s*$', p)) else '' for p in params]
    body = source[opening + 1:end - 1]
    cbody = clean[opening + 1:end - 1]
    # the loop: `label: { ... } if (X != &OBJ) goto label;` or `do { ... } while (X != &OBJ);`
    found = None
    for m in re.finditer(rf'(?m)^[ \t]*({ID}):[ \t]*\{{', cbody):
        stop = close(cbody, m.end() - 1, '{', '}')
        tail = re.match(rf'\s*if\s*\(\s*({ID})\s*!=\s*&\s*(sp[0-9A-F]+)\s*\)\s*goto\s+{m[1]}\s*;', cbody[stop:]) if stop else None
        if tail:
            found = (m.start(), m.end(), stop, stop + tail.end(), tail[1], tail[2])
            break
    if not found:
        for m in re.finditer(r'\bdo\s*\{', cbody):
            stop = close(cbody, m.end() - 1, '{', '}')
            tail = re.match(rf'\s*while\s*\(\s*({ID})\s*!=\s*&\s*(sp[0-9A-F]+)\s*\)\s*;', cbody[stop:]) if stop else None
            if tail:
                found = (m.start(), m.end(), stop, stop + tail.end(), tail[1], tail[2])
                break
    if not found:
        return []
    start, inner_start, inner_end, loop_end, test_var, test_obj = found
    inner = body[inner_start:inner_end - 1]
    before = body[:start]
    if re.search(r'\b(?:continue|break|goto|return)\b', cbody[inner_start:inner_end]):
        return []
    # each cursor: its step, and where the target starts
    steps = {}
    lines = inner.split('\n')
    for number, line in enumerate(lines):
        m = re.fullmatch(rf'\s*({ID})\s*\+=\s*({NUM})\s*;\s*', line)
        if m and m[1] not in steps:
            steps[m[1]] = (_int(m[2]), number)
    bases = {}
    for m in re.finditer(rf'\b({ID})\s*=\s*&\s*(sp[0-9A-F]+)\s*;', before):
        bases[m[1]] = ('obj', int(m[2][2:], 16))
    for m in re.finditer(rf'\b({ID})\s*=\s*({ID})\s*;', before):
        if m[2] in names:
            bases[m[1]] = ('arg', m[2])
    if test_var not in steps or bases.get(test_var, ('',))[0] != 'obj' or steps[test_var][0] <= 0:
        return []
    count, rest = divmod(int(test_obj[2:], 16) - bases[test_var][1], steps[test_var][0])
    if rest or not 2 <= count <= 64:
        return []
    cursors = set(bases)  # (a cursor set up before the loop that the loop doesn't step is not understood)
    if cursors != set(steps) or len(cursors) < 2:
        return []

    def access(var, number, line):
        """Rewrite one cursor's accesses in a statement as `(kind, type, byte offset from the cursor's start)`."""
        stride, step_line = steps[var]
        shift = stride if number > step_line else 0
        hits = []
        pattern = (rf'\*\(({ID}(?:\s+{ID})?)\s*\*\)\s*\(\s*\(char\s*\*\)\s*\(\s*(?:\(unsigned short\)\s*)?{re.escape(var)}\s*\)\s*\+\s*({NUM})\s*\)'
                   rf'|\*\(({ID})\s*\*\)\s*{re.escape(var)}\b')
        for m in re.finditer(pattern, line):
            hits.append((m.start(), m.end(), m[1] or m[3], _int(m[2]) + shift if m[2] else shift))
        return hits

    # every mention of a cursor must be a plain access (or its own step / the end test)
    new_lines = []
    types = {}
    for number, line in enumerate(lines):
        if any(re.fullmatch(rf'\s*{re.escape(v)}\s*\+=\s*{NUM}\s*;\s*', line) for v in steps):
            continue
        replaced = line
        for var in sorted(cursors, key=len, reverse=True):
            hits = access(var, number, replaced)
            for a, b, kind, offset in reversed(hits):
                if bases[var][0] == 'obj':
                    stride = steps[var][0]
                    width = SIZES.get(kind.replace('unsigned ', 'u').replace('signed ', 's').strip())
                    if not width or stride % width or offset % width:
                        return []
                    types.setdefault(bases[var][1], kind)
                    if types[bases[var][1]] != kind:
                        return []
                    scale, plus = stride // width, offset // width
                    index = ('i' if scale == 1 else f'i*{scale}') + (f'+{plus}' if plus > 0 else f'{plus}' if plus < 0 else '')
                    text = f'sp{bases[var][1]:X}[{index}]'
                else:
                    stride = steps[var][0]
                    if kind != 'u8':
                        return []
                    text = f'{bases[var][1]}[i*{stride}' + (f'+{offset}' if offset > 0 else f'{offset}' if offset < 0 else '') + ']'
                replaced = replaced[:a] + text + replaced[b:]
        if any(re.search(rf'\b{re.escape(v)}\b', replaced) for v in cursors):
            return []
        new_lines.append(replaced)
    # stack objects: heads are the walked bases and the objects whose address the function takes
    declared = {int(m[3], 16): m[1] for m in DECL.finditer(before)}
    walked = {bases[v][1] for v in cursors if bases[v][0] == 'obj'}
    taken = {int(m[1], 16) for m in re.finditer(r'&\s*sp([0-9A-F]+)\b', before + body[loop_end:])}
    heads = walked | taken
    if not heads or not (heads - walked) <= set(declared):
        return []
    ordered = sorted(heads)
    run_end = ordered[-1] + SIZES.get(declared.get(ordered[-1], ''), 0)
    while run_end in declared and run_end not in heads:  # the scalars that follow the last head, back to back
        run_end += SIZES.get(declared[run_end], 0) or 1 << 20
    extents = {off: (ordered[k + 1] if k + 1 < len(ordered) else run_end) - off for k, off in enumerate(ordered)}
    arrays = {}
    for off, extent in extents.items():
        kind = types.get(off) or declared.get(off)
        width = SIZES.get(kind or '', 0)
        if not width or extent % width or extent // width < 2:
            return []
        arrays[off] = (kind, extent // width)
    absorbed = {}  # scalars inside a head's extent (`spD6` becomes `spD0[3]`)
    for off, kind in declared.items():
        if off in arrays:
            continue
        owner = max((h for h in arrays if h < off), default=None)
        if owner is None or off >= owner + arrays[owner][1] * SIZES[arrays[owner][0]] or not SIZES.get(kind):
            return []
        absorbed[off] = (owner, (off - owner) // SIZES[arrays[owner][0]])
    if {*walked} & set(absorbed) or int(test_obj[2:], 16) not in heads:
        return []
    if any(count * steps[v][0] > extents[bases[v][1]] for v in cursors if bases[v][0] == 'obj'):
        return []  # (a cursor would walk off its object)
    byte_params = {bases[v][1] for v in cursors if bases[v][0] == 'arg'}

    def tidy(text):
        for off, (owner, index) in sorted(absorbed.items(), reverse=True):
            text = re.sub(rf'\bsp{off:X}\b', f'sp{owner:X}[{index}]', text)
        for off in arrays:  # the head used as a scalar is its first element; its address is the array itself
            text = re.sub(rf'&\s*sp{off:X}\b', f'@@{off:X}', text)
            text = re.sub(rf'\bsp{off:X}\b(?!\s*\[)', f'sp{off:X}[0]', text)
            text = text.replace(f'@@{off:X}', f'sp{off:X}')
        for var in byte_params:
            text = re.sub(rf'\*\(u8\s*\*\)\s*\(\s*\(char\s*\*\)\s*\(\s*{var}\s*\)\s*\+\s*(\d+)\s*\)', rf'{var}[\1]', text)
            text = re.sub(rf'\*\(u8\s*\*\)\s*{var}\b', rf'{var}[0]', text)
        return text

    pre, post = before, body[loop_end:]
    pre = DECL.sub(lambda m: '' if int(m[3], 16) in declared else m[0], pre)
    for var in cursors:
        pre = re.sub(rf'(?m)^[ \t]*[A-Za-z_][\w \t]*\*[ \t]*{re.escape(var)}[ \t]*;[ \t]*\n', '', pre)
        pre = re.sub(rf'(?m)^[ \t]*{re.escape(var)}[ \t]*=[^;\n]*;[ \t]*\n', '', pre)
    if re.search(r'\bi\b', pre + post):
        return []
    pre, post = tidy(pre), tidy(post)
    arguments = call_arguments(asm, names)
    if arguments:  # the stack arguments the draft's call never had, from the target's stores to its argument slots
        def widen(m):
            given = [a for a in m[3].split(',') if a.strip()]
            if len(given) >= 4 + len(arguments) or len(given) < 4:
                return m[0]
            more = [re.sub(r'^&(sp[0-9A-F]+)$', lambda n: n[1] if int(n[1][2:], 16) in arrays else n[0], a)
                    for a in arguments[len(given) - 4:]]
            return f'{m[1]}{m[2]}({m[3].rstrip()}, {", ".join(more)});'
        post = re.sub(rf'(?m)^([ \t]*)({ID})\(([^;\n]*)\);', widen, post, count=1)
    declarations = ''.join(f'    {kind} sp{off:X}[{n}];\n' for off, (kind, n) in sorted(arrays.items(), reverse=True)) + '    s32 i;\n'
    temps = [m[1] for m in re.finditer(r'(?m)^[ \t]*(?:u8|s8|u16|s16|s32|u32|int)[ \t]+(temp_\w+)[ \t]*;[ \t]*\n', pre)]
    folded = _sorted_runs(_inline_temps([l for l in new_lines if l.strip()], temps))
    gone = [t for t in temps if not any(re.search(rf'\b{t}\b', l) for l in folded)]
    for t in gone:
        pre = re.sub(rf'(?m)^[ \t]*(?:u8|s8|u16|s16|s32|u32|int)[ \t]+{t}[ \t]*;[ \t]*\n', '', pre)
    pre = re.sub(r'\n{3,}', '\n\n', pre).strip('\n')
    result = []
    for swap in (False, True):
        loop_lines = [_swap_or(l) if swap else l for l in folded]
        header = '\n'.join(_swap_or(l) if swap and re.match(r'\s*sp[0-9A-F]+\[\d+\]\s*=', l) else l for l in pre.split('\n'))
        loop = f'    for (i = 0; i < {count}; i++) {{\n' + '\n'.join(loop_lines) + '\n    }\n'
        text = (source[:opening + 1] + '\n' + declarations + header + '\n' + loop + post.lstrip('\n').rstrip(' ') + source[end - 1:])
        for var in byte_params:
            text = re.sub(rf'\b(?:void|char|u8|s8)\s*\*\s*{var}\b', f'u8 *{var}', text, count=1)
        result.append((FAMILY, text))
    return result
