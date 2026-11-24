"""Loop invariants that GCC 2.7.2 spills, written the way the compiler makes them: plain locals, in slot order.

A KMC GCC 2.7.2 loop function (`-O2`, N64) whose target stored `n - 1` and `flags & 1` to stack words before its loop
and reloaded them with `lw $v1` inside it. m2c wrote the two words as fields of its frame union (`view_spC74`,
`view_spC7C`), which gives `$v0` and a frame the size of the union. They are not variables: loop.c hoisted two
loop-invariant pseudos and global.c, out of saved registers, spilled the lowest-priority ones; reload uses `$v1` as its
spill register. Four facts decide the source (each measured on that function, 379 -> 30 -> 0; the notes are in
decompdecomp's docs/learnings/finding/hoisted-invariant-spill-slots.md):

- Each spilled pseudo takes an 8-byte slot after the locals (function.c `assign_stack_local`, align -1), in ascending
  pseudo number, so a union sized to the whole frame counts them twice: take the union down to the slots' start.
- A local assigned a constant that cse folds away still keeps a slot (stale reference count, a hypothesis): the
  target's third, never-accessed slot was such a local, and it has to be declared *after* the locals whose slots come
  first (declared in the loop, or first, it gave none or the wrong order).
- A `do { } while (0)` around the hoisted expression raises its weight, so it takes a saved register instead.
- With the invariant a simple local, `a && b` folds to a branch-free `and`; nested `if`s keep the target's two
  branches. And a pointer walked by `p += 4` makes loop.c's giv initialisation come before the hoisted ops, where the
  indexed form `((T *)base)[i + k]` puts it after them, as in the target.

`spilled_view_local` turns a union member that is only read and written as a scalar, and lies past every member whose
address is taken, into a plain local and shrinks the union; `late_constant_local` declares a zero local last and
compares against it; `walk_index_form` writes the walked pointer's store as an indexed one; `nested_and_if` splits an
`&&` condition; `spilled_invariant_combined` applies all four. The judge decides.

`nested_and_if` offered only the first four `&&` conditions in the function. `!(v & A) && !(v & B)` is one such
condition that combine.c folds to a single `andi v, A|B` test where the target has two `andi`/`bnel` pairs: those come
first, unlimited, and `nested_mask_tests` nests every one at once (a 1928-instruction collision sweep, KMC gcc 2.7.2,
two such tests past the first four `if`s: each alone 19232 -> 18792 / 18917, both 18477)."""
import re

from .integer_repair_support import edit, view

FAMILIES = ('spilled_view_local', 'late_constant_local', 'walk_index_form', 'nested_and_if', 'spilled_invariant_combined',
            'address_load_order', 'mask_test_order', 'nested_mask_tests')
VIEW, ZERO, WALK, NEST, COMBINED, LOADS, MASKS, NEST_MASKS = FAMILIES
MASK_TEST = re.compile(r'^!\s*\(\s*(\w+)\s*&\s*(?:0x[0-9A-Fa-f]+|\d+)\s*\)$')
LIMIT = 4
SCALARS = ('s32', 'u32', 'int', 'long')
SIZES = {'f32': 4, 's32': 4, 'u32': 4, 'int': 4, 'float': 4, 's16': 2, 'u16': 2, 'short': 2, 's8': 1, 'u8': 1, 'char': 1}


def _balanced(text, start, open_='{', close='}'):
    """Index just past the group opened at `start`, or -1."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == open_:
            depth += 1
        elif text[index] == close:
            depth -= 1
            if depth == 0:
                return index + 1
    return -1


def _body(source, name):
    part = view(source, name)
    return (part.opening + 1, part.end - 1) if part else None


def _union(source, lo, hi):
    """(start, end, variable, bytes_size_match, members) of the function's frame union, members as
    (name, pad, type, start, end)."""
    found = re.search(r'\bunion\s*\{', source[lo:hi])
    if not found:
        return None
    open_ = lo + found.end() - 1
    close = _balanced(source, open_)
    tail = re.match(r'\s*(\w+)\s*;', source[close:])
    if close < 0 or not tail:
        return None
    inner = source[open_:close]
    size = re.search(r'u8\s+bytes\[(\d+)\]\s*;', inner)
    members = []
    for member in re.finditer(r'struct\s*\{\s*(?:u8\s+pad\[(\d+)\]\s*;\s*)?(\w+)\s+value\s*;\s*\}\s*(\w+)\s*;', inner):
        members.append((member[3], int(member[1] or 0), member[2], open_ + member.start(), open_ + member.end()))
    return (found.start() + lo, close + tail.end(), tail[1], size, members, open_)


def _unwrap(text, names):
    """`do { ... } while (0);` groups that contain an assignment to one of `names`, replaced by their contents."""
    pattern = re.compile(r'\bdo\s*\{')
    position = 0
    while True:
        found = pattern.search(text, position)
        if not found:
            return text
        open_ = found.end() - 1
        close = _balanced(text, open_)
        tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', text[close:]) if close > 0 else None
        inner = text[open_ + 1:close - 1] if tail else ''
        if tail and any(re.search(rf'\b{re.escape(name)}\s*=[^=]', inner) for name in names):
            text = text[:found.start()] + inner.strip() + text[close + tail.end():]
            position = found.start()
        else:
            position = found.end()


def spilled_view_local(source, name):
    body = _body(source, name)
    union = body and _union(source, *body)
    if not union:
        return None
    start, end, var, size, members, _ = union
    taken = [m for m in members if re.search(rf'&\s*{re.escape(var)}\s*\.\s*{re.escape(m[0])}\b', source)]
    if not taken or not size:
        return None
    reach = max(pad + 4 for _, pad, _, _, _ in taken)
    chosen = [m for m in members if m not in taken and m[1] >= reach and m[2] in SCALARS
              and re.search(rf'\b{re.escape(var)}\s*\.\s*{re.escape(m[0])}\s*\.\s*value\b', source)]
    if not chosen:
        return None
    new = {m[0]: f'spill_{m[1] + 16:X}' for m in chosen}
    text = source
    uses = re.compile(rf'\b{re.escape(var)}\s*\.\s*(\w+)\s*\.\s*value\b')
    text = uses.sub(lambda match: new.get(match[1], match[0]), text)
    union = _union(text, *_body(text, name))
    start, end, var, size, members, open_ = union
    drops = [(m[3], m[4], '') for m in members if m[0] in new]
    keep = min(m[1] for m in chosen) // 8 * 8
    if keep < reach:
        return None
    drops.append((open_ + size.start(), open_ + size.end(), f'u8 bytes[{keep}];'))
    text = edit(text, drops)
    union = _union(text, *_body(text, name))
    declarations = ''.join(f'\n  {m[2]} {new[m[0]]};' for m in sorted(chosen, key=lambda m: m[1]))
    text = text[:union[1]] + declarations + text[union[1]:]
    return _unwrap(text, new.values())


def late_constant_local(source, name):
    body = _body(source, name)
    if not body:
        return []
    lo, hi = body
    text = source
    out = []
    union = _union(text, lo, hi)
    scan = union[1] if union else lo
    declaration = re.compile(r'^[ \t]*(?:register\s+)?(?:unsigned\s+|signed\s+)?(?:long\s+)?(?!return\b|goto\b|else\b)\w+[ \t*]+\w+(?:\[\d+\])?[ \t]*;[ \t]*$')
    where = scan
    for line in re.finditer(r'[^\n]*\n|[^\n]+$', text[scan:hi]):
        stripped = line[0].strip()
        if stripped == '' or declaration.match(line[0].rstrip('\n')):
            where = scan + line.end()
            continue
        break
    sites = [m for m in re.finditer(r'\bif\s*\(\s*([\w.\[\]>-]+)\s*>\s*0\s*\)', text[where:hi])]
    for site in sites[:LIMIT]:
        s = where + site.start()
        if re.search(r'\blate_zero\b', text):
            return []
        indent = re.match(r'[ \t]*', text[text.rfind('\n', 0, s) + 1:s])[0]
        line_start = text.rfind('\n', 0, s) + 1
        compare = text[s:where + site.end()].replace('> 0', '> late_zero')
        changed = text[:line_start] + f'{indent}late_zero = 0;\n' + indent + compare + text[where + site.end():]
        changed = changed[:where] + 'int late_zero;\n' + changed[where:] if where == scan else changed
        if where != scan:
            changed = changed[:where] + '  int late_zero;\n' + changed[where:]
        out.append(changed)
    return out


def walk_index_form(source, name):
    body = _body(source, name)
    if not body:
        return []
    lo, hi = body
    text = source[lo:hi]
    store = re.compile(
        r'(?P<counter>\w+)\s*\+=\s*1\s*;(?P<gap>\s*)\*\(\(\s*(?P<type>\w+)\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P<ptr>\w+)\)\s*\+\s*'
        r'(?P<off>0[xX][0-9a-fA-F]+|\d+)\)\)\s*=\s*(?P<value>[^;]+);\s*(?P=ptr)\s*=\s*(?P=ptr)\s*\+\s*(?P<step>\d+)\s*;')
    out = []
    for found in store.finditer(text):
        size = SIZES.get(found['type'])
        offset, step = int(found['off'], 0), int(found['step'])
        if not size or step != size or offset % size:
            continue
        ptr = found['ptr']
        init = re.search(rf'\b{ptr}\s*=\s*(\w+)\s*;', text)
        if not init or len(re.findall(rf'\b{ptr}\b', text)) != 4 + len(re.findall(rf'(?:void|char)\s*\*\s*{ptr}\b', text)):
            continue
        base = init[1]
        replacement = f'(({found["type"]} *) {base})[{found["counter"]} + {offset // size}] = {found["value"].strip()}; {found["counter"]} += 1;'
        edits = [(found.start(), found.end(), replacement), (init.start(), init.end(), '')]
        decl = re.search(rf'^[ \t]*(?:void|char)\s*\*\s*{ptr}\s*;[ \t]*\n', text, re.M)
        if decl:
            edits.append((decl.start(), decl.end(), ''))
        out.append(source[:lo] + edit(text, edits) + source[hi:])
    return out


def nested_and_if(source, name):
    """Each `if (a && b) {..}` without an else as nested ifs: the two-mask tests of one variable first, then the
    first LIMIT others."""
    masks = []
    others = _nested_and_if(source, name, masks)
    firsts = [source[:start] + new + source[end:] for start, end, new in masks]
    return firsts + [text for text in others if text not in firsts][:LIMIT]


def nested_mask_tests(source, name):
    """Every `!(v & A) && !(v & B)` condition nested at once (outermost edits only, applied from the end)."""
    masks = []
    _nested_and_if(source, name, masks)
    if len(masks) < 2:
        return None
    text = source
    for start, end, new in sorted(masks, reverse=True):
        if any(s2 < start and end <= e2 for s2, e2, _ in masks):
            continue  # nested inside another edit: it is redone on the next run
        text = text[:start] + new + text[end:]
    return text


def _nested_and_if(source, name, masks=None):
    body = _body(source, name)
    if not body:
        return []
    lo, hi = body
    out = []
    for found in re.finditer(r'\bif\s*\(', source[lo:hi]):
        start = lo + found.start()
        open_ = lo + found.end() - 1
        close = _balanced(source, open_, '(', ')')
        condition = source[open_ + 1:close - 1]
        depth, cut = 0, None
        for index, char in enumerate(condition):
            depth += char == '('
            depth -= char == ')'
            if depth == 0 and condition[index:index + 2] == '&&':
                if cut is not None:
                    cut = -1
                    break
                cut = index
        if not cut or cut < 0 or '||' in condition:
            continue
        block = re.match(r'\s*\{', source[close:])
        if not block:
            continue
        brace = close + block.end() - 1
        end = _balanced(source, brace)
        if end < 0 or re.match(r'\s*else\b', source[end:]):
            continue
        left, right = condition[:cut].strip(), condition[cut + 2:].strip()
        for part_ in ('left', 'right'):
            value = locals()[part_]
            if value.startswith('(') and _balanced(value, 0, '(', ')') == len(value):
                if part_ == 'left':
                    left = value[1:-1].strip()
                else:
                    right = value[1:-1].strip()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        inner = source[brace:end]
        new = f'if ({left})\n{indent}{{\n{indent}  if ({right})\n{indent}  {inner}\n{indent}}}'
        a, b = MASK_TEST.match(left), MASK_TEST.match(right)
        if masks is not None and a and b and a[1] == b[1]:
            masks.append((start, end, new))
        out.append(source[:start] + new + source[end:])
    return out


def address_load_order(source, name):
    """A run of `a = U.view_x.value;` loads from the frame union, put in the order of the members' offsets."""
    body = _body(source, name)
    union = body and _union(source, *body)
    if not union:
        return []
    var, offsets = union[2], {m[0]: m[1] for m in union[4]}
    line = re.compile(rf'^([ \t]*)(\w+)\s*=\s*{re.escape(var)}\s*\.\s*(\w+)\s*\.\s*value\s*;[ \t]*\n', re.M)
    out, position = [], 0
    while True:
        found = line.search(source, position)
        if not found:
            return out
        run = [found]
        while (nxt := line.match(source, run[-1].end())):
            run.append(nxt)
        position = run[-1].end()
        keys = [offsets.get(m[3]) for m in run]
        if len(run) < 2 or None in keys or keys == sorted(keys):
            continue
        ordered = sorted(run, key=lambda m: offsets[m[3]])
        out.append(source[:run[0].start()] + ''.join(m[0] for m in ordered) + source[position:])


def mask_test_order(source, name):
    """Adjacent `if (x & MASK) { one statement }` blocks (a local assigned `x & MASK` counts), in ascending mask order."""
    body = _body(source, name)
    if not body:
        return []
    lo, hi = body
    text = source
    masks = {m[1]: int(m[2], 0) for m in re.finditer(r'\b(\w+)\s*=\s*\w+\s*&\s*(0[xX][0-9a-fA-F]+|\d+)\s*;', text[lo:hi]) for m in [(m[0], m[1], m[2])]}
    head = re.compile(r'[ \t]*if\s*\(')
    out, position = [], lo
    while (found := re.compile(r'[ \t]*if\s*\(').search(text, position, hi)):
        run, cursor = [], found.start()
        while (start := head.match(text, cursor)):
            close = _balanced(text, start.end() - 1, '(', ')')
            brace = re.compile(r'\s*\{').match(text, close)
            end = _balanced(text, brace.end() - 1) if brace else -1
            if end < 0 or re.compile(r'\s*else\b').match(text, end):
                break
            condition = text[start.end():close - 1].strip()
            literal = re.fullmatch(r'\(?\s*\w+\s*&\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)?', condition)
            mask = int(literal[1], 0) if literal else masks.get(condition.strip('() '))
            if mask is None or text[brace.end():end - 1].count(';') != 1:
                break
            run.append((mask, cursor, end))
            gap = re.compile(r'\s*').match(text, end)
            cursor = gap.end()
            if not head.match(text, cursor):
                break
            cursor = head.match(text, cursor).start()
        position = (run[-1][2] if run else found.end())
        if len(run) >= 2 and [r[0] for r in run] != sorted(r[0] for r in run) and len({r[0] for r in run}) == len(run):
            pieces = [text[r[1]:r[2]] for r in run]
            gaps = [text[run[i][2]:run[i + 1][1]] for i in range(len(run) - 1)] + ['']
            ordered = [pieces[i] for i in sorted(range(len(run)), key=lambda i: run[i][0])]
            joined = ''.join(piece + gap for piece, gap in zip(ordered, gaps))
            out.append(text[:run[0][1]] + joined + text[run[-1][2]:])
    return out[:LIMIT]


def combined(source, name):
    text = spilled_view_local(source, name)
    if not text:
        return None
    for step in (late_constant_local, walk_index_form, nested_and_if, address_load_order, mask_test_order):
        for _ in range(4):  # one child per run or site: apply them in turn
            children = step(text, name)
            if not children:
                break
            text = children[0]
    return text


def variants(source, name, header=''):
    out = []
    one = spilled_view_local(source, name)
    if one:
        out.append((VIEW, one))
    out += [(ZERO, text) for text in late_constant_local(source, name)]
    out += [(WALK, text) for text in walk_index_form(source, name)]
    every = nested_mask_tests(source, name)
    if every:
        out.append((NEST_MASKS, every))
    out += [(NEST, text) for text in nested_and_if(source, name)]
    out += [(LOADS, text) for text in address_load_order(source, name)]
    out += [(MASKS, text) for text in mask_test_order(source, name)]
    whole = combined(source, name)
    if whole and whole != source:
        out.append((COMBINED, whole))
    return [(family, text) for family, text in out if text != source]
