"""Counted loops written the way the original compiler's input was: `for` loops over one shared counter.

m2c turns each `for (i = 0; i < n; i++)` into a guard and a `do`/`while`, gives every loop its own counter name, walks a
pointer where the original indexed, and keeps an explicit stride variable where the original multiplied the counter.
gcc 2.7.2 (`-O2`, MIPS) keeps what the source shape implies: one pseudo per source variable, and a pre-test `for` loop
leaves a trace that the rotated `do` does not. A texture-loader-sized N64 function (four counted loops over a header
table, one of them inside the other) went 99 -> 0 through the steps below; none of them was offered by an earlier family
(the saved best only reached 79 from the existing ones), and every one of the nine was needed (each removed from the
matching source put the score back to a nonzero number, from 5 to 210). The mechanisms are hypotheses from measured
frames and cc1's `-dl -dg` tables, not read from the compiler's source:

* `counted_for_loop`: `i = 0; if (n != 0) { do { ...; i += 1; } while (i < n); }` as `for (i = 0; i < n; i += 1)`.
  Each pre-test loop of the matching source added eight bytes to the frame with no `sp` access (cc1 listed an
  unallocated temporary with no uses, a spill slot reload had reserved), so four loops were the 0x20 bytes the draft
  had been padding with an unused array. `counted_for_loop_frame` converts every loop and drops that array as one
  child: neither is better alone (the loops alone grow the frame past the target's; the array alone keeps the wrong
  slot order, the spills above it instead of below).
* `loop_pointer_to_index`: a pointer walked beside the counter (`p = base; ... *p ... p += 1; i += 1;`) written
  `base[i]`. The giv loop.c makes from the index is the pointer the target walks, with the priority the counter's uses
  give it; the explicit pointer left the saved registers swapped (210 against 0).
* `loop_stride_from_counter`: an explicit stride (`s = 0; ... s += 12;`) written `i * 12`, so loop.c makes the giv.
* `loop_counter_share`: the later loops' counters merged into the first loop's (priority is uses over live length of one
  pseudo; separate counters took caller-saved registers where the target keeps one saved register).
* `scaled_address_accumulate`: `v = i * 8; t = v + p;` as `v = i * 8; v += (s32) p;` (the sum lands in the dying
  scaled register).
* `integer_address_sum`: a pointer assigned `i * 12 + (*field)` as `(void *) (i * 12 + (s32) (*field))` (the operand
  order of the add).
* `product_shift_in_arm`: `v = (a * b) >> 1; if (c) { ... (a * b) >> 1 ... }` as `v = a * b; if (c) { v >>= 1; ... v ... }`
  (the shift is computed where the flag is dead, and shares the product's register).
* `limit_sum_operand_casts`: `(u32) (a + b)` in a pointer-limit compare as `(u32) a + (u32) b`.

All of them are proposals: they are tried against the exact judge, one at a time and as one chain
(`counted_loop_chain`).
"""
import re
from functools import lru_cache

from .integer_repair_support import edit, view
from .pattern_repairs import close

FOR = 'counted_for_loop'
FOR_ALL = 'counted_for_loop_all'
FOR_FRAME = 'counted_for_loop_frame'
INDEX = 'loop_pointer_to_index'
STRIDE = 'loop_stride_from_counter'
SHARE = 'loop_counter_share'
ACCUMULATE = 'scaled_address_accumulate'
ADDRESS_SUM = 'integer_address_sum'
SHIFT = 'product_shift_in_arm'
CASTS = 'limit_sum_operand_casts'
CHAIN = 'counted_loop_chain'
FAMILIES = (FOR, FOR_ALL, FOR_FRAME, INDEX, STRIDE, SHARE, ACCUMULATE, ADDRESS_SUM, SHIFT, CASTS, CHAIN)
IDENT = r'[A-Za-z_]\w*'
UNSIGNED = re.compile(r'^(?:unsigned\b.*|u(?:8|16|32|64)|size_t)$')
NUMERIC_CAST = re.compile(r'\(\s*(?:(?:unsigned|signed)\s+(?:char|short|int|long)|[us](?:8|16|32|64)|int|long|char|short|unsigned)\s*\)')


def _core(text):
    """An expression with its integer casts, parentheses and spaces removed, to compare two spellings of it."""
    text = re.sub(r'\s+', '', text)
    text = NUMERIC_CAST.sub('', text)
    return text.replace('(', '').replace(')', '')


def _decl_type(clean, name):
    hit = re.search(rf'(?m)^[ \t]*((?:[A-Za-z_]\w*[ \t]+)*[A-Za-z_]\w*[ \t]*\**)[ \t]*(?<![\w])\**{re.escape(name)}[ \t]*;', clean)
    return re.sub(r'\s+', ' ', hit[1]).strip() if hit else None


def _assigned(clean, name, start, end):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?<![\w.>])(?:\+\+|--)\s*{re.escape(name)}\b'
                     rf'|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', clean[start:end]) is not None


def _step(text):
    """The counter a trailing `i++;` / `++i;` / `i += 1;` / `i = i + 1;` steps, and where the statement starts."""
    for pattern in (rf'({IDENT})\s*\+\+\s*;\s*$', rf'\+\+\s*({IDENT})\s*;\s*$', rf'({IDENT})\s*\+=\s*1\s*;\s*$'):
        hit = re.search(r'(?<![\w.>])' + pattern, text)
        if hit:
            return hit[1], hit.start()
    hit = re.search(rf'(?<![\w.>])({IDENT})\s*=\s*\1\s*\+\s*1\s*;\s*$', text)
    return (hit[1], hit.start()) if hit else (None, None)


class Loop:
    """A counted loop: either m2c's guarded `do`/`while` or a `for (i = 0; test; i += 1) { ... }`."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    @property
    def body(self):
        return self.part.clean[self.body_start:self.body_end]


def _bound(test):
    hit = re.match(r'\s*\(*\s*(?:\(\s*\w+\s*\)\s*)?\(*\s*(' + IDENT + r')\s*\)*\s*<\s*(.+?)\s*$', test, re.S)
    return (hit[1], hit[2]) if hit else (None, None)


_IF = re.compile(r'\bif\s*\(')
_FOR = re.compile(r'\bfor\s*\(')
_OPEN = re.compile(r'\s*\{')
_DO_BLOCK = re.compile(r'\bdo\s*\{')
_GUARD_HEAD = re.compile(r'\s*((?:' + IDENT + r'\s*=\s*[^;{}]+;\s*)*)do\s*\{')
_WHILE = re.compile(r'\s*while\s*\(')
_END = re.compile(r'\s*;\s*\}')
_FOR_INIT = re.compile(r'\s*(' + IDENT + r')\s*=\s*0\s*')


def _loops(part):
    """Every guarded `do` loop and every `for (i = 0; ...)` loop in the function, in order.

    Seven families ask for the same function's loops, so the answer is kept for the last few sources and handed out as
    new `Loop` objects (callers may change theirs). The scan matches in place (`pattern.match(text, pos, endpos)`)
    instead of slicing the rest of the function for every `if`, and passes over any `if` block that holds no `do {`."""
    fields = _scan(part.source, part.clean, part.opening, part.end)
    return [Loop(part=part, **found) for found in fields]


@lru_cache(maxsize=16)
def _scan(source, clean, opening, end):
    found = []
    for guard in _IF.finditer(clean, opening, end):
        at = guard.start()
        cond_end = close(clean, guard.end() - 1)
        if cond_end is None:
            continue
        brace = _OPEN.match(clean, cond_end)
        if not brace:
            continue
        block_open = brace.end() - 1
        block_end = close(clean, block_open, '{', '}')
        if block_end is None:
            continue
        # the block must begin with assignments and then `do {`: a block with no `do {` at all cannot
        if not _DO_BLOCK.search(clean, block_open + 1, block_end):
            continue
        head = _GUARD_HEAD.match(clean, block_open + 1, block_end)
        if not head:
            continue
        brace_at = head.end() - 1
        body_close = close(clean, brace_at, '{', '}')
        tail = _WHILE.match(clean, body_close) if body_close else None
        if not tail:
            continue
        test_open = tail.end() - 1
        test_end = close(clean, test_open)
        after = _END.match(clean, test_end) if test_end else None
        if not after or after.end() != block_end:
            continue
        test = clean[test_open + 1:test_end - 1]
        counter, bound = _bound(test)
        if not counter:
            continue
        found.append(dict(kind='guarded', start=at, end=block_end, guard=clean[guard.end():cond_end - 1],
                          pre=clean[block_open + 1:head.start(1) + len(head[1])].strip() if head[1] else '',
                          pre_span=(head.start(1), head.end(1)),
                          body_start=brace_at + 1, body_end=body_close - 1, test=test, test_span=(test_open + 1, test_end - 1),
                          counter=counter, bound=bound))
    for loop in _FOR.finditer(clean, opening, end):
        at = loop.start()
        head_end = close(clean, loop.end() - 1)
        if head_end is None:
            continue
        header = clean[loop.end():head_end - 1].split(';')
        brace = _OPEN.match(clean, head_end)
        if len(header) != 3 or not brace:
            continue
        brace_at = brace.end() - 1
        body_close = close(clean, brace_at, '{', '}')
        counter, bound = _bound(header[1])
        init = _FOR_INIT.fullmatch(header[0])
        if body_close is None or not counter or not init or init[1] != counter:
            continue
        found.append(dict(kind='for', start=at, end=body_close, guard=None, pre='', pre_span=None, body_start=brace_at + 1,
                          body_end=body_close - 1, test=header[1].strip(), counter=counter, bound=bound))
    return tuple(sorted(found, key=lambda loop: loop['start']))


def _statements(clean, start, end):
    """Top-level statements of a block as (start, end) spans; nested blocks stay inside their statement."""
    spans = []
    pos = start
    while pos < end:
        while pos < end and clean[pos].isspace():
            pos += 1
        if pos >= end:
            break
        depth = 0
        at = pos
        while pos < end:
            char = clean[pos]
            if char in '({[':
                depth += 1
            elif char in ')}]':
                depth -= 1
                if char == '}' and depth == 0:
                    pos += 1
                    # a block statement ends at its brace unless an `else` or a `while (...);` follows
                    tail = re.match(r'\s*(?:else\b|while\b)', clean[pos:end])
                    if not tail:
                        break
                    continue
            elif char == ';' and depth == 0:
                pos += 1
                break
            pos += 1
        spans.append((at, pos))
    return spans


def _counter_init(loop):
    """The `i = 0;` before a guarded loop that nothing reassigns before it, and whether it can go."""
    clean = loop.part.clean
    inits = list(re.finditer(rf'(?<![\w.>]){re.escape(loop.counter)}\s*=\s*0\s*;', clean[loop.part.opening:loop.start]))
    if not inits:
        return None
    hit = inits[-1]
    first, last = loop.part.opening + hit.start(), loop.part.opening + hit.end()
    if _assigned(clean, loop.counter, last, loop.start):
        return None
    return first, last, not clean[last:loop.start].strip()


def _unsigned_counter(loop):
    kind = _decl_type(loop.part.clean, loop.counter)
    return bool(kind and UNSIGNED.match(kind))


def _guard_matches(loop):
    """The guard is the loop test at i == 0: `n != 0`, `n` or `0 < n` for the test's own bound (or a local copy of it)."""
    guard = re.sub(r'\s+', '', loop.guard)
    guard = re.sub(r'^\((.*)\)$', r'\1', guard)
    operand = re.sub(r'(?:!=0|>0)$', '', guard) if re.search(r'(?:!=0|>0)$', guard) else None
    if operand is None:
        hit = re.fullmatch(r'0<(.+)', guard) or re.fullmatch(r'0!=(.+)', guard)
        operand = hit[1] if hit else guard
    bound = _core(loop.bound)
    if _core(operand) == bound:
        return True
    if re.fullmatch(IDENT, operand):
        clean = loop.part.clean
        for hit in re.finditer(rf'(?<![\w.>]){re.escape(operand)}\s*=\s*([^;]+);', clean[loop.part.opening:loop.start]):
            if _core(hit[1]) == bound:
                return True
    return False


def for_edits(loop):
    """Edits that write one guarded loop as a `for`, or None."""
    if loop.kind != 'guarded' or not _unsigned_counter(loop) or not _guard_matches(loop):
        return None
    clean = loop.part.clean
    inside = clean[loop.body_start:loop.body_end]
    counter, at = _step(inside)
    if counter != loop.counter or re.search(r'\b(?:continue|goto)\b', inside) or not re.search(rf'(?<![\w.>]){re.escape(counter)}\b', loop.test):
        return None
    init = _counter_init(loop)
    if not init:
        return None
    source = loop.part.source
    body = source[loop.body_start:loop.body_start + at].rstrip()
    pre = source[loop.pre_span[0]:loop.pre_span[1]].strip()
    pre = pre + '\n' if pre else ''
    test = source[loop.test_span[0]:loop.test_span[1]].strip()
    text = f'{pre}for ({counter} = 0; {test}; {counter} += 1) {{\n{body}\n}}'
    edits = [(loop.start, loop.end, text)]
    if init[2]:
        edits.append((init[0], init[1], ''))
    return edits


def _single(source, name):
    part = view(source, name)
    if not part:
        return []
    return [(loop, for_edits(loop)) for loop in _loops(part) if loop.kind == 'guarded']


def for_variants(source, name):
    done = [(loop, edits) for loop, edits in _single(source, name) if edits]
    out = [(FOR, edit(source, edits)) for _, edits in done[:4]]
    if len(done) > 1:
        out.append((FOR_ALL, edit(source, [e for _, edits in done for e in edits])))
    return out


def _unused_arrays(part):
    """Local arrays the function names only in their declaration: padding the draft added."""
    found = []
    for decl in re.finditer(r'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t]+)+(' + IDENT + r')\[\d+\][ \t]*;[ \t]*\n', part.clean[part.opening:part.end]):
        if len(re.findall(rf'(?<![\w.>]){re.escape(decl[1])}\b', part.clean[part.opening:part.end])) == 1:
            found.append((part.opening + decl.start(), part.opening + decl.end()))
    return found


def frame_variants(source, name):
    part = view(source, name)
    done = [(loop, edits) for loop, edits in _single(source, name) if edits]
    if not part or not done:
        return []
    arrays = _unused_arrays(part)
    if not arrays:
        return []
    edits = [e for _, edits in done for e in edits] + [(start, end, '') for start, end in arrays[:1]]
    return [(FOR_FRAME, edit(source, edits))]


def _types_equal(clean, first, second):
    one, two = _decl_type(clean, first), _decl_type(clean, second)
    return bool(one and one == two and one.endswith('*'))


def _uses(text, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', text)]


def index_variants(source, name):
    """`p = base; ... *p ... p += 1; i += 1;` written `base[i]` with the counter's step last."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for loop in _loops(part):
        if loop.kind != 'guarded' or not loop.pre:
            continue
        inside = clean[loop.body_start:loop.body_end]
        for init in re.finditer(rf'({IDENT})\s*=\s*({IDENT})\s*;', clean[loop.pre_span[0]:loop.pre_span[1]]):
            pointer, base = init[1], init[2]
            if not _types_equal(clean, pointer, base) or _assigned(clean, base, loop.body_start, loop.body_end):
                continue
            spans = _statements(clean, loop.body_start, loop.body_end)
            steps = [s for s in spans if re.fullmatch(rf'\s*(?:{re.escape(pointer)}\s*\+=\s*1\s*;|{re.escape(pointer)}\s*\+\+\s*;|\+\+\s*{re.escape(pointer)}\s*;)', clean[s[0]:s[1]])]
            counts = [s for s in spans if re.fullmatch(rf'\s*(?:{re.escape(loop.counter)}\s*\+=\s*1\s*;|{re.escape(loop.counter)}\s*\+\+\s*;|\+\+\s*{re.escape(loop.counter)}\s*;)', clean[s[0]:s[1]])]
            if len(steps) != 1 or len(counts) != 1 or steps[0] != spans[-1] or len(_uses(inside, loop.counter)) != 1:
                continue
            derefs = len(re.findall(rf'\*\s*{re.escape(pointer)}\b', inside))
            if not derefs or len(_uses(inside, pointer)) != derefs + 1:
                continue
            edits = [(loop.pre_span[0] + init.start(), loop.pre_span[0] + init.end(), '')]
            for use in re.finditer(rf'\*\s*{re.escape(pointer)}\b', inside):
                edits.append((loop.body_start + use.start(), loop.body_start + use.end(), f'{base}[{loop.counter}]'))
            edits.append((counts[0][0], counts[0][1], ''))
            edits.append((steps[0][0], steps[0][1], f'{loop.counter} += 1;'))
            decl = re.search(rf'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t]+)*[A-Za-z_]\w*[ \t]*\**[ \t]*{re.escape(pointer)}[ \t]*;[ \t]*\n', clean[part.opening:part.end])
            if decl and len(_uses(clean[part.opening:part.end], pointer)) == len(_uses(inside, pointer)) + 2:
                edits.append((part.opening + decl.start(), part.opening + decl.end(), ''))
            out.append((INDEX, edit(source, edits)))
    return out[:3]


def stride_variants(source, name):
    """`s = 0; ... s += K;` beside a counted loop's counter, written `i * K` where `s` is read."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for loop in _loops(part):
        inside = clean[loop.body_start:loop.body_end]
        pre = clean[loop.pre_span[0]:loop.pre_span[1]] if loop.pre_span else ''
        for init in re.finditer(rf'({IDENT})\s*=\s*0\s*;', pre):
            stride = init[1]
            spans = _statements(clean, loop.body_start, loop.body_end)
            steps = [(s, re.fullmatch(rf'\s*{re.escape(stride)}\s*\+=\s*(0[xX][0-9a-fA-F]+|\d+)\s*;', clean[s[0]:s[1]])) for s in spans]
            steps = [(s, m) for s, m in steps if m]
            counts = [s for s in spans if re.fullmatch(rf'\s*(?:{re.escape(loop.counter)}\s*\+=\s*1\s*;|{re.escape(loop.counter)}\s*\+\+\s*;)', clean[s[0]:s[1]])]
            if len(steps) != 1 or len(counts) != 1:
                continue
            tail = min(steps[0][0][0], counts[0][0])
            reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(stride)}\b', inside) if loop.body_start + m.start() < tail]
            if not reads or len(reads) + 1 != len(_uses(inside, stride)):
                continue
            constant = steps[0][1][1]
            edits = [(loop.pre_span[0] + init.start(), loop.pre_span[0] + init.end(), ''), (steps[0][0][0], steps[0][0][1], '')]
            for read in reads:
                before = inside[:read.start()].rstrip()[-1:]
                after = inside[read.end():].lstrip()[:1]
                wrap = before in '*/%.>' and before != '' or after in '*/%.[' and after != ''
                text = f'{loop.counter} * {constant}'
                edits.append((loop.body_start + read.start(), loop.body_start + read.end(), f'({text})' if wrap else text))
            decl = re.search(rf'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t]+)*[A-Za-z_]\w*[ \t]*\**[ \t]*{re.escape(stride)}[ \t]*;[ \t]*\n', clean[part.opening:part.end])
            if decl and len(_uses(clean[part.opening:part.end], stride)) == len(_uses(inside, stride)) + 2:
                edits.append((part.opening + decl.start(), part.opening + decl.end(), ''))
            out.append((STRIDE, edit(source, edits)))
    return out[:3]


def share_variants(source, name):
    """Counters of later loops renamed to the first loop's counter when they are the same type and live only in their loops."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    loops = _loops(part)
    if len(loops) < 2:
        return []
    first = loops[0]
    function = clean[part.opening:part.end]
    edits = []
    merged = []
    for late in dict.fromkeys(loop.counter for loop in loops[1:]):
        group = [loop for loop in loops[1:] if loop.counter == late]
        if (late == first.counter or late in merged or not _decl_type(clean, late)
                or _decl_type(clean, late) != _decl_type(clean, first.counter)):
            continue
        mentions = [part.opening + m for m in _uses(function, late)]
        covered = 0
        spans = []
        for loop in group:
            init = _counter_init(loop) if loop.kind == 'guarded' else None
            covered += len(_uses(clean[loop.start:loop.end], late)) + (1 if init else 0)
            spans.append((loop, init))
        if covered != len(mentions) - 1 or any(m < first.end for m in mentions[1:]):
            continue
        merged.append(late)
        for loop, init in spans:
            for m in re.finditer(rf'(?<![\w.>]){re.escape(late)}\b', clean[loop.start:loop.end]):
                edits.append((loop.start + m.start(), loop.start + m.end(), first.counter))
            if init:
                edits.append((init[0], init[0] + len(late), first.counter))
        decl = re.search(rf'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t]+)*[A-Za-z_]\w*[ \t]*{re.escape(late)}[ \t]*;[ \t]*\n', function)
        if decl:
            edits.append((part.opening + decl.start(), part.opening + decl.end(), ''))
    return [(SHARE, edit(source, edits))] if edits else []


def accumulate_variants(source, name):
    """`v = i * 8; t = v + p;` as `v = i * 8; v += (s32) p;`, the later reads of `t` reading `v`."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for loop in _loops(part):
        spans = _statements(clean, loop.body_start, loop.body_end)
        for first, second in zip(spans, spans[1:]):
            one = re.fullmatch(rf'\s*({IDENT})\s*=\s*({IDENT})\s*\*\s*(0[xX][0-9a-fA-F]+|\d+)\s*;', clean[first[0]:first[1]])
            two = re.fullmatch(rf'\s*({IDENT})\s*=\s*{re.escape(one[1]) if one else "@"}\s*\+\s*(.+);', clean[second[0]:second[1]], re.S) if one else None
            if not one or not two or one[2] != loop.counter:
                continue
            scaled, target = one[1], two[1]
            if len(_uses(clean[loop.body_start:loop.body_end], scaled)) != 2 or scaled == target:
                continue
            if (_decl_type(clean, scaled) or '*').endswith('*') or not (_decl_type(clean, target) or '').endswith('*'):
                continue
            after = re.search(rf'(?<![\w.>]){re.escape(target)}\b\s*(=?)', clean[loop.end:part.end])
            if after and after[1] != '=':
                continue
            edits = [(second[0], second[1], f'{scaled} += (s32) ({source[second[0]:second[1]].split("+", 1)[1].strip().rstrip(";").strip()});')]
            for use in re.finditer(rf'(?<![\w.>]){re.escape(target)}\b', clean[second[1]:loop.body_end]):
                edits.append((second[1] + use.start(), second[1] + use.end(), scaled))
            out.append((ACCUMULATE, edit(source, edits)))
    return out[:3]


def _pointer_sum(text):
    """`A + B` at the top level, as the two operands, or None."""
    depth = 0
    for index, char in enumerate(text):
        depth += char == '('
        depth -= char == ')'
        if depth == 0 and char == '+' and text[index - 1] != '+' and text[index + 1:index + 2] != '+':
            return text[:index].strip(), text[index + 1:].strip()
    return None


def address_sum_variants(source, name):
    """`t = i * 12 + (*field);` with `t` a pointer, written `t = (void *) (i * 12 + (s32) (*field));`."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for loop in _loops(part):
        for stmt in _statements(clean, loop.body_start, loop.body_end):
            hit = re.fullmatch(rf'\s*({IDENT})\s*=\s*(.+);', clean[stmt[0]:stmt[1]], re.S)
            if not hit or not (_decl_type(clean, hit[1]) or '').endswith('*'):
                continue
            sides = _pointer_sum(hit[2])
            if not sides:
                continue
            product = [side for side in sides if re.fullmatch(rf'\(*{re.escape(loop.counter)}\s*\*\s*(?:0[xX][0-9a-fA-F]+|\d+)\)*', side)]
            loaded = [side for side in sides if side.startswith('(*') or side.startswith('*')]
            if len(product) != 1 or len(loaded) != 1:
                continue
            kind = _decl_type(clean, hit[1]).rsplit('*', 1)[0].strip() + ' *'
            sum_text = f'{product[0]} + (s32) {loaded[0]}' if sides[0] == product[0] else f'(s32) {loaded[0]} + {product[0]}'
            out.append((ADDRESS_SUM, edit(source, [(stmt[0], stmt[1], f'{hit[1]} = ({kind}) ({sum_text});')])))
    return out[:3]


def _flexible(text):
    """A regex matching `text` up to whitespace."""
    return r'\s*'.join(re.escape(token) for token in re.findall(r'\w+|[^\w\s]', text))


def shift_variants(source, name):
    """`v = X >> n; if (c) { ... X >> n ... }` as `v = X; if (c) { v >>= n; ... v ... }`."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    spans = _statements(clean, part.opening + 1, part.end - 1)
    blocks = []
    for loop in _loops(part):
        blocks.append(_statements(clean, loop.body_start, loop.body_end))
    blocks.append(spans)
    for stmts in blocks:
        for first, second in zip(stmts, stmts[1:]):
            one = re.fullmatch(rf'\s*({IDENT})\s*=\s*(.+?)\s*>>\s*(\d+)\s*;', clean[first[0]:first[1]], re.S)
            if not one or not re.match(r'\s*if\s*\(', clean[second[0]:second[1]]):
                continue
            variable, product, amount = one[1], one[2], one[3]
            kind = _decl_type(clean, variable)
            if not kind or not UNSIGNED.match(kind):
                continue
            whole = f'{product} >> {amount}'
            pattern = re.compile(r'\(\s*' + _flexible(whole) + r'\s*\)|' + _flexible(whole))
            arm = clean[second[0]:second[1]]
            brace = arm.find('{')
            if brace < 0 or len(pattern.findall(arm)) < 1 or variable in arm:
                continue
            edits = [(first[0], first[1], f'{variable} = {source[first[0]:first[1]].split("=", 1)[1].rsplit(">>", 1)[0].strip()};')]
            edits.append((second[0] + brace + 1, second[0] + brace + 1, f'\n{variable} >>= {amount};'))
            for use in pattern.finditer(arm[brace + 1:]):
                edits.append((second[0] + brace + 1 + use.start(), second[0] + brace + 1 + use.end(), variable))
            out.append((SHIFT, edit(source, edits)))
    return out[:3]


def casts_variants(source, name):
    """`< (u32) (a + b)` as `< (u32) a + (u32) b`."""
    part = view(source, name)
    if not part:
        return []
    edits = []
    for hit in re.finditer(rf'(?<=<)\s*\(\s*\(\s*u32\s*\)\s*\(\s*\(?\s*({IDENT})\s*\)?\s*\+\s*({IDENT})\s*\)\s*\)', part.clean[part.opening:part.end]):
        edits.append((part.opening + hit.start(), part.opening + hit.end(), f' ((u32) {hit[1]} + (u32) {hit[2]})'))
    return [(CASTS, edit(source, edits[:1]))] if edits else []


STEPS = (index_variants, stride_variants, share_variants, for_variants, frame_variants, accumulate_variants, address_sum_variants,
         shift_variants, casts_variants)


def chain_variants(source, name):
    """Every step above applied in turn, each repeated while it still finds a loop to rewrite, as one child.

    The loops are converted and the unused frame array dropped in one step (`counted_for_loop_frame`) when there is an
    array to drop, and as plain `for` loops otherwise."""
    text = source
    for step in STEPS:
        for _ in range(6):
            if step is for_variants:
                found = [v for family, v in frame_variants(text, name)] or [v for family, v in step(text, name) if family == FOR_ALL] or [v for _, v in step(text, name)]
            elif step is frame_variants:
                break
            else:
                found = [v for _, v in step(text, name)]
            if not found or found[0] == text:
                break
            text = found[0]
    return [(CHAIN, text)] if text != source else []


def variants(source, name):
    out = []
    for step in STEPS:
        out += step(source, name)
    out += chain_variants(source, name)
    return out
