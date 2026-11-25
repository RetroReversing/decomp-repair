"""A second cursor kept beside a pointer, folded back into offsets from the one pointer.

m2c and long searches leave a derived pointer next to the one it was cut from:

    var_q = var_p + 2;                      /* or `helper(var_p)` for an `x + 2` helper */
    do {
        ... var_q[-1] ... var_q[0] ...      /* the second and third element of the record */
        var_p += 3; var_i += 1;             /* the record pointer and the loop counter */
    } while (var_i < n);                    /* or: `var_q += 3;` beside `var_p += 3;` in each arm */

The game had one pointer. GCC 2.7.2's loop pass cuts a pointer like `var_q` itself from `var_p[1]` and `var_p[2]`
(`loop.c`: a DEST_ADDR giv with a non-zero constant is reduced to a register of its own, and the two addresses are
combined into one with the offsets -1 and 0), so the source's second pointer is not needed to get the target's. It
costs a plain program: a user variable is a pointer the compiler keeps (so the stepping order and the register order
follow the source, not the loop pass), and any increment pair written for it is another thing the scheduler orders
(a saved best with three such cursors was at 410: written back as plain offsets it was at 125 after the loop's other
steps, 0 with them).

`variants` writes the function with every cursor it can prove folded, and each cursor alone:
  * `q = p + K;` (or `q = helper(p);` where `helper` is an inline `return arg + K;`: the typed step, since the helper
    went through bytes) and no other write of `q` but `q += n;`, every use `q[<index>]` with a literal index (a call of
    an inline helper that returns a literal counts, and so does `(cast)(i * M) + c` for a loop counter `i`).
  * lockstep: each `q += n;` is preceded in straight-line code of the same block by `p += n;` and nothing else writes
    `p` between `q = ...` and the last `q`; the `p += n;` is dropped and the `q += n;` becomes `p += n;`
    (so reads of `p` between the two move by `n`), and `q[c]` becomes `p[K + c]`;
  * counter: `q` is never stepped, the uses are `q[i * M + c]` before the loop's one `p += M;`, `i` is set to 0 before
    `q = p + K;` and stepped by one in the same block as that `p += M;`: `q[i * M + c]` is `p[K + c]`.
Every rule keeps the program's meaning (the first one is a hypothesis for a helper applied to a wider type: the
step the helper stood for); the exact judge decides.

A long search's spelling of the same cursor goes through bytes: `void *q;`, `q = ((char *) p) + 4;`, reads
`*((u16 *) (((char *) q) + (-2)))` and `((Field_u16 *) (((char *) q) + 0))->v`, and `q += 6;` beside `p += 3;` in
either order. `_typed` writes such a cursor in elements first (`u16 *q; q = p + 2; q[-1]; q[0]; p += 3; q += 3;`) when
every offset and step is a multiple of the element and `p` points to that element, and the rules above fold it. On a
1928-instruction collision sweep two such cursors of a ray walk with a plane fallback (four reads each) folded into
`tri[1]`, `tri[2]`: 4687 -> 4192. loop.c combines the givs `tri + 2` and `tri + 4` into one register with the offsets
-2 and 0 (`combine_givs_p`); a cursor of its own is a biv, and its second address became a third register."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'cursor_lockstep_fold'
FAMILIES = (FAMILY,)
NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)'
CONTROL = re.compile(r'\b(?:case|default|break|goto|return|continue|if|else|for|while|do|switch)\b|[{}]')
CASTS = r'(?:unsigned\s+(?:char|short|int|long)|signed\s+(?:char|short|int|long)|[su](?:8|16|32)|int|long|short|char)'


def _number(text):
    """A C integer literal's value, with the sign a helper's `return -0xA0;` carries (the helper's body is `-0xA0`, which
    `int(text, 16)` rejects, and the crash stopped the whole local repair pass)."""
    sign, digits = (-1, text[1:].lstrip()) if text.startswith('-') else (1, text)
    return sign * int(digits, 16 if digits.lower().startswith('0x') else 10)


def _helpers(clean):
    """name -> ('lit', value) for `T name(void) { return LIT; }`, ('add', K) for `T *name(T *x) { return x + K; }`."""
    found = {}
    pattern = re.compile(rf'(?:static\s+|inline\s+)*[\w\s*]+?\b({IDENT})\s*\(([^)]*)\)\s*{{\s*return\s+([^;{{}}]+);\s*}}')
    for hit in pattern.finditer(clean):
        name, params, body = hit[1], hit[2].strip(), hit[3].strip()
        if params in ('', 'void'):
            if re.fullmatch(rf'-?\s*{NUMBER}', body):
                found[name] = ('lit', _number(body.replace(' ', '')))
        else:
            parameter = re.search(rf'({IDENT})\s*$', params)
            add = re.fullmatch(rf'{re.escape(parameter[1])}\s*\+\s*({NUMBER})', body) if parameter else None
            if add and ',' not in params:
                found[name] = ('add', _number(add[1]))
    return found


def _linear(text, counters):
    """`text` as (constant, {counter: coefficient}) or None: literals, +, -, *, parentheses, casts to integer types and
    the counters named in `counters`."""
    text = re.sub(rf'\(\s*{CASTS}\s*\)', '', text)
    tokens = re.findall(rf'{NUMBER}|{IDENT}|[-+*()]', text)
    if ''.join(tokens) != re.sub(r'\s+', '', text):
        return None
    at = [0]

    def peek():
        return tokens[at[0]] if at[0] < len(tokens) else None

    def take():
        at[0] += 1
        return tokens[at[0] - 1]

    def expression():
        value = term()
        while peek() in ('+', '-'):
            sign = 1 if take() == '+' else -1
            other = term()
            if value is None or other is None:
                return None
            value = {key: value.get(key, 0) + sign * other.get(key, 0) for key in set(value) | set(other)}
        return value

    def term():
        value = unary()
        while peek() == '*':
            take()
            other = unary()
            if value is None or other is None:
                return None
            if set(value) <= {''}:
                value, other = other, value
            if not set(other) <= {''}:
                return None
            factor = other.get('', 0)
            value = {key: coefficient * factor for key, coefficient in value.items()}
        return value

    def unary():
        token = peek()
        if token == '-':
            take()
            value = unary()
            return None if value is None else {key: -coefficient for key, coefficient in value.items()}
        if token == '+':
            take()
            return unary()
        if token == '(':
            take()
            value = expression()
            if peek() != ')':
                return None
            take()
            return value
        if token is None:
            return None
        take()
        if re.fullmatch(NUMBER, token):
            return {'': _number(token)}
        if token in counters:
            return {token: 1}
        return None

    try:
        value = expression()
    except (IndexError, TypeError):
        return None
    if value is None or at[0] != len(tokens):
        return None
    return {key: coefficient for key, coefficient in value.items() if coefficient or key == ''}


def _blocks(clean, base, end):
    """[(start, stop)] of every brace block in clean[base:end]."""
    stack, out = [], []
    for hit in re.finditer(r'[{}]', clean[base:end]):
        if hit[0] == '{':
            stack.append(base + hit.start())
        elif stack:
            out.append((stack.pop(), base + hit.end()))
    return out


def _innermost(blocks, at):
    inside = [block for block in blocks if block[0] < at < block[1]]
    return min(inside, key=lambda block: block[1] - block[0]) if inside else None


def _statement_span(clean, start, stop):
    """The statement at [start, stop) widened to its whole line when it is alone on it, else to the spaces after it."""
    line = clean.rfind('\n', 0, start) + 1
    tail = clean.find('\n', stop)
    tail = len(clean) if tail < 0 else tail
    if not clean[line:start].strip() and not clean[stop:tail].strip():
        return line, min(tail + 1, len(clean))
    after = stop
    while after < len(clean) and clean[after] in ' \t':
        after += 1
    return start, after


def _fold(clean, base, end, helpers, pointer, keep=False):
    """The edits that fold the cursor `pointer` (a dict from `_cursors`) into the pointer it was cut from, or None."""
    q, init = pointer['name'], pointer['init']
    uses, steps = [], []
    for m in re.finditer(rf'(?<![\w.>]){re.escape(q)}\b', clean[base:end]):
        at = base + m.start()
        if init[0] <= at < init[1] or pointer['declaration'][0] <= at < pointer['declaration'][1]:
            continue
        step = re.match(rf'{re.escape(q)}\s*(?:\+=\s*({NUMBER})|\+\+)\s*;', clean[at:end])
        if step:
            steps.append((at, at + step.end(), _number(step[1]) if step[1] else 1))
            continue
        use = re.match(rf'{re.escape(q)}\s*\[', clean[at:end])
        if not use:
            return None
        open_at = at + use.end() - 1
        stop = close(clean, open_at, '[', ']')
        if not stop:
            return None
        uses.append((at, stop, clean[open_at + 1:stop - 1]))
    if not uses:
        return None
    last = max(item[1] for item in uses + [(0, e, 0) for _, e, _ in steps])
    region = (init[1], last)
    for a, b, _ in uses:
        if region[0] > a:
            return None
    blocks = _blocks(clean, base, end)
    if steps:
        return _lockstep(clean, base, helpers, pointer, uses, steps, region, keep)
    return _counter(clean, base, end, helpers, pointer, uses, blocks)


def _index_value(text, helpers, counters):
    text = re.sub(rf'\b({IDENT})\s*\(\s*\)', lambda m: str(helpers[m[1]][1]) if helpers.get(m[1], ('',))[0] == 'lit' else m[0], text)
    return _linear(text, counters)


def _writes(clean, name, lo, hi):
    """[(start, stop, n)] of every write of `name` in clean[lo:hi]; None when a write is not `+= literal`."""
    found = []
    for m in re.finditer(rf'(?<![\w.>*&])(?:\+\+\s*{re.escape(name)}\b|{re.escape(name)}\b\s*(?:\+\+|--|[-+*/|&^]?=(?!=)|<<=|>>=))', clean[lo:hi]):
        at = lo + m.start()
        stop = clean.find(';', at)
        text = clean[at:stop + 1]
        plus = re.fullmatch(rf'(?:{re.escape(name)}\s*\+=\s*({NUMBER})|{re.escape(name)}\s*\+\+|\+\+\s*{re.escape(name)})\s*;', text)
        if not plus:
            return None
        found.append((at, stop + 1, _number(plus[1]) if plus[1] else 1))
    return found


def _lockstep(clean, base, helpers, pointer, uses, steps, region, keep=False):
    p, K = pointer['base'], pointer['offset']
    # q's own writes are only the steps; p's writes inside the region are exactly the paired increments
    paired = []
    writes = _writes(clean, p, region[0], region[1])
    if writes is None:
        return None
    for step in steps:
        before = [w for w in writes if w[1] <= step[0] and w[2] == step[2] and w not in [x[0] for x in paired]]
        if not before:
            return None
        write = before[-1]
        if CONTROL.search(clean[write[1]:step[0]]):
            return None
        paired.append((write, step))
    if len(paired) != len(writes):
        return None
    new = []
    for (write, step) in paired:
        n = write[2]
        window = clean[write[1]:step[0]]
        if keep:
            # the pointer's own step stays where it is and the cursor's goes: `p += 3; i++; q += 3;` -> `p += 3; i++;`
            # (reads of `p` between them already see the advanced pointer)
            new.append(_statement_span(clean, step[0], step[1]) + ('',))
            continue
        # reads of p between the two statements see the advanced p; they move by n
        for m in re.finditer(rf'(?<![\w.>]){re.escape(p)}\b', window):
            at = write[1] + m.start()
            tail = clean[at + len(p):step[0]]
            index = re.match(r'\s*\[', tail)
            if index:
                stop = close(clean, at + len(p) + index.end() - 1, '[', ']')
                if not stop:
                    return None
                inner = clean[at + len(p) + index.end():stop - 1]
                literal = re.fullmatch(NUMBER, inner.strip())
                new.append((at + len(p) + index.end(), stop - 1,
                            str(_number(inner.strip()) + n) if literal else f'{inner.strip()} + {n}'))
            elif re.search(r'\*\s*$', clean[max(base, at - 2):at]) and not re.search(r'[\w)\]]\s*\*\s*$', clean[max(base, at - 12):at]):
                new.append((at - len(clean[max(base, at - 2):at]) + len(clean[max(base, at - 2):at].rstrip('* ')), at + len(p), f'{p}[{n}]'))
            else:
                return None
        low, high = _statement_span(clean, write[0], write[1])
        new.append((low, high, ''))
        new.append((step[0], step[1], f'{p} += {n};' if n != 1 else f'{p}++;'))
    windows = [(write[1], step[0]) for write, step in paired]
    for at, stop, text in uses:
        # every paired write sits next to its step (checked above), so outside those windows `q` is `p + K`, also
        # in a branch nested before the step (a ray walk's plane fallback); inside one, `p` is `p + K` only when its
        # step moves down to the cursor's
        if keep and any(lo <= at < hi for lo, hi in windows):
            return None
        value = _index_value(text, helpers, ())
        if value is None or set(value) != {''}:
            return None
        new.append((at, stop, f'{p}[{K + value[""]}]'))
    return new


def _counter(clean, base, end, helpers, pointer, uses, blocks):
    p, K = pointer['base'], pointer['offset']
    loops = [b for b in blocks if re.search(r'\bdo\s*$', clean[max(base, b[0] - 60):b[0]])
             and re.match(r'\s*while\b', clean[b[1]:b[1] + 40]) and all(b[0] < at and stop < b[1] for at, stop, _ in uses)]
    if not loops:
        return None
    outer = min(loops, key=lambda b: b[1] - b[0])
    region = (pointer['init'][1], outer[1])
    writes = _writes(clean, p, region[0], region[1])
    if not writes or len(writes) != 1:
        return None
    write = writes[0]
    M = write[2]
    counters = set()
    for at, stop, text in uses:
        counters |= {w for w in re.findall(IDENT, re.sub(rf'\(\s*{CASTS}\s*\)', '', text)) if w not in helpers}
    if len(counters) != 1:
        return None
    counter = counters.pop()
    steps = _writes(clean, counter, region[0], region[1])
    if not steps or len(steps) != 1 or steps[0][2] != 1:
        return None
    if _innermost(blocks, steps[0][0]) != _innermost(blocks, write[0]):
        return None
    reset = list(re.finditer(rf'(?<![\w.>]){re.escape(counter)}\s*=\s*0\s*;', clean[base:pointer['init'][0]]))
    if not reset or _writes(clean, counter, base + reset[-1].end(), pointer['init'][0]) != []:
        return None
    # the loop leaves only by its test: no `continue`, `return`, or a goto to a label outside it
    body = clean[outer[0]:outer[1]]
    if re.search(r'\b(?:continue|return)\b', body):
        return None
    if any(not re.search(rf'\b{g}\s*:', body) for g in re.findall(r'\bgoto\s+(\w+)', body)):
        return None
    new = []
    for at, stop, text in uses:
        if stop > write[0]:
            return None
        value = _index_value(text, helpers, {counter})
        if value is None or set(value) - {'', counter} or value.get(counter, 0) != M:
            return None
        new.append((at, stop, f'{p}[{K + value.get("", 0)}]'))
    return new


def _cursors(clean, base, end, helpers, parameters=()):
    """Every pointer local `q` initialised once as `q = p + K` / `q = helper(p)`."""
    out = []
    declaration = re.compile(rf'(?m)^[ \t]*((?:register\s+)?(?:unsigned\s+)?{IDENT})[ \t]*\*[ \t]*({IDENT})[ \t]*(=[^;\n]*)?;[ \t]*\n')
    every = {m[2]: (base + m.start(), base + m.end(), m[1]) for m in declaration.finditer(clean[base:end])}
    pointers = {m[2]: (base + m.start(), base + m.end(), m[1]) for m in declaration.finditer(clean[base:end]) if not m[3]}
    for name in parameters:
        every.setdefault(name, (base, base, ''))
    for q, spot in pointers.items():
        inits = list(re.finditer(rf'(?<![\w.>*]){re.escape(q)}\s*=\s*([^;=]+);', clean[base:end]))
        inits = [m for m in inits if not re.search(r'[=!<>]\s*$', clean[max(base, base + m.start() - 1):base + m.start()])]
        if len(inits) != 1:
            continue
        text = inits[0][1].strip()
        found = re.fullmatch(rf'({IDENT})\s*\+\s*({NUMBER})', text)
        offset = None
        if found:
            p, offset = found[1], _number(found[2])
        else:
            call = re.fullmatch(rf'({IDENT})\s*\(\s*({IDENT})\s*\)', text)
            if call and helpers.get(call[1], ('',))[0] == 'add':
                p, offset = call[2], helpers[call[1]][1]
        if offset is None or p not in every or p == q:
            continue
        out.append({'name': q, 'base': p, 'offset': offset, 'declaration': spot,
                    'init': (base + inits[0].start(), base + inits[0].end())})
    return out


SIZES = {'u8': 1, 's8': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4, 'f32': 4}
OFFSET = r'(\(\s*-?\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)\s*\)|-?\s*(?:0[xX][0-9a-fA-F]+|[0-9]+))'


def _byte_reads(q):
    char = rf'\(\s*\(\s*\(\s*char\s*\*\s*\)\s*{re.escape(q)}\s*\)\s*\+\s*{OFFSET}\s*\)'
    return re.compile(rf'\*\s*\(\s*\(\s*({IDENT})\s*\*\s*\)\s*{char}\s*\)|\(\s*\(\s*Field_({IDENT})\s*\*\s*\)\s*{char}\s*\)\s*->\s*v')


def _signed(text):
    text = text.replace(' ', '').strip('()')
    return -_number(text[1:]) if text.startswith('-') else _number(text)


def _typed(source, name):
    """The function with each byte-addressed cursor written in elements, or None when there is none (docstring)."""
    part = view(source, name)
    if not part:
        return None
    clean = part.clean
    base, end = part.opening + 1, part.end - 1
    body = clean[base:end]
    changes = []
    for decl in re.finditer(rf'(?m)^[ \t]*(?:void|char)[ \t]*\*[ \t]*({IDENT})[ \t]*;[ \t]*\n', body):
        q = decl[1]
        init = list(re.finditer(rf'(?<![\w.>*]){q}\s*=\s*\(\s*\(\s*char\s*\*\s*\)\s*({IDENT})\s*\)\s*\+\s*({NUMBER})\s*;', body))
        if len(init) != 1:
            continue
        p, K = init[0][1], _number(init[0][2])
        ptype = re.search(rf'(?m)^[ \t]*({IDENT})[ \t]*\*[ \t]*{re.escape(p)}[ \t]*;', body)
        if not ptype or ptype[1] not in SIZES:
            continue
        T, size = ptype[1], SIZES[ptype[1]]
        mentions = {base + m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(q)}\b', body)}
        covered = {base + init[0].start(), base + decl.start(1)}
        edits, ok = [], K % size == 0
        for m in _byte_reads(q).finditer(body):
            kind, offset = (m[1], m[2]) if m[1] else (m[3], m[4])
            value = _signed(offset)
            if kind != T or value % size:
                ok = False
                break
            edits.append((base + m.start(), base + m.end(), f'{q}[{value // size}]'))
            covered |= {at for at in mentions if base + m.start() <= at < base + m.end()}
        for m in re.finditer(rf'(?<![\w.>*]){re.escape(q)}\s*\+=\s*({NUMBER})\s*;', body):
            n = _number(m[1])
            if n % size:
                ok = False
                break
            covered.add(base + m.start())
            # `q += 6; p += 3;` side by side becomes `p += 3; q += 3;`: the order the lockstep rule reads
            after = re.match(rf'(\s*){re.escape(p)}\s*\+=\s*({NUMBER})\s*;', body[m.end():])
            if after and _number(after[2]) == n // size:
                edits.append((base + m.start(), base + m.end() + after.end(), f'{p} += {n // size};{after[1]}{q} += {n // size};'))
            else:
                edits.append((base + m.start(), base + m.end(), f'{q} += {n // size};'))
        if not ok or not edits or mentions - covered:
            continue
        edits.append((base + init[0].start(), base + init[0].end(), f'{q} = {p} + {K // size};'))
        edits.append((base + decl.start(), base + decl.end(), re.sub(r'(?:void|char)(?=[ \t]*\*)', T, decl[0], count=1)))
        changes.extend(edits)
    if not changes or not _consistent(changes):
        return None
    return edit(source, changes)


def variants(source, name):
    found = _variants(source, name)
    typed = _typed(source, name)
    if typed is not None:
        seen = {text for _, text in found}
        found += [(family, text) for family, text in _variants(typed, name) if text not in seen and text != source]
    return found


def _variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    base, end = part.opening + 1, part.end - 1
    helpers = _helpers(_blank(source))
    folds = []
    header = clean[:part.opening]
    parameters = re.findall(rf'\*\s*({IDENT})\s*(?:,|$)', header[header.rindex('(') + 1:].rstrip().rstrip(')')) if '(' in header else []
    for pointer in _cursors(clean, base, end, helpers, parameters):
        if re.search(rf'&\s*{re.escape(pointer["name"])}\b|&\s*{re.escape(pointer["base"])}\b', clean[base:end]):
            continue
        drop = [_statement_span(clean, *pointer['init']) + ('',), pointer['declaration'][:2] + ('',)]
        moved = _fold(clean, base, end, helpers, pointer)
        kept = _fold(clean, base, end, helpers, pointer, keep=True)
        options = [fold + drop for fold in (moved, kept) if fold is not None]
        if options:
            folds.append(options)
    if not folds:
        return []
    out = []
    if len(folds) > 1:
        for choice in (0, -1):
            together = [change for options in folds for change in options[choice]]
            if _consistent(together):
                out.append(edit(source, together))
    out.extend(edit(source, fold) for options in folds for fold in options)
    seen, result = set(), []
    for text in out:
        if text not in seen and text != source:
            seen.add(text)
            result.append((FAMILY, text))
    return result


def _consistent(edits):
    """No two edits overlap (two folds that touch the same statement are offered one at a time)."""
    spans = sorted((a, b) for a, b, _ in edits)
    return all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 97}
