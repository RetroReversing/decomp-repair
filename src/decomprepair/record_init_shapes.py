"""Three shapes of a record-initialising loop that GCC 2.7.2 (KMC) schedules differently from m2c's spelling.

A function that clears 56 records in a do/while loop and then sets a few globals was 300 off and exact after four
small edits; none was a rewrite the library had:

* `counter_stride_inline`: m2c keeps the record's byte offset as a second induction variable beside the counter
  (`n += 1; off += 0xD4;`). The game indexed by the counter, `base + n * 0xD4`, and GCC's strength reduction made the
  offset register itself: its `move $a0, $zero` then sits after the hoisted loop constants instead of before them.
  A call after the loop that was passed the dead offset (`f(off)` to an unprototyped `f()`) loses that argument too,
  since the game's call had none.
* `call_window_global_local`: a global pointer read two or more times between two calls, held in a local from just
  after the first call. GCC loads it once there, and the scheduler then places the load (and the `li` of the call's
  first argument) where the game had them; written out each time the load sat later (240 -> 60).
* `staged_float_constant`: GCC hoists a loop's constants in the order the loop first uses them, and its scheduler puts
  a store that needs a long-lived register where the register was loaded. A `999.0f` store written after the next
  address temporary, with the constant assigned to a local where the store was, moves the constant's first use ahead
  of the byte `0xFF` the target hoists after it (60 -> 0). Both halves are needed: sunk alone, the hoist order flips.

Each family is offered only where the shape is there; the judge's byte comparison decides whether it helps.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

ID = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][\da-fA-F]+|[1-9]\d*|0)'
KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'else', 'do'}

COUNTER_STRIDE = 'counter_stride_inline'
CALL_WINDOW = 'call_window_global_local'
STAGED_FLOAT = 'staged_float_constant'
FAMILIES = (COUNTER_STRIDE, CALL_WINDOW, STAGED_FLOAT)


def _function(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (clean, opening, end) if end else None


def _increment(var, step):
    """The statement that advances `var` by `step`, in m2c's and in the permuter's spelling."""
    return (rf'\b{var}\s*(?:\+=\s*{step}|=\s*{var}\s*\+\s*{step}|\+\+)\s*;' if step == '1'
            else rf'\b{var}\s*(?:\+=\s*{step}|=\s*{var}\s*\+\s*{step})\s*;')


def counter_stride_inline(source, name, arch, asm):
    """Index a do/while loop's records by its counter instead of a second, byte-offset induction variable."""
    if arch != 'mips' or not (found := _function(source, name)):
        return []
    clean, start, end = found
    loop = re.compile(rf'\bdo\s*{{(?P<body>[^{{}}]*)}}\s*while\s*\(\s*(?P<count>{ID})\s*<\s*(?P<bound>{NUM})\s*\)\s*;')
    target = re.sub(r'/\*[^\n]*?\*/', '', asm or '')
    for hit in loop.finditer(clean, start, end):
        body, count = hit['body'], hit['count']
        for step in re.finditer(rf'\b(?P<off>{ID})\s*(?:\+=\s*|=\s*(?P=off)\s*\+\s*)(?P<stride>{NUM})\s*;', body):
            off, stride = step['off'], int(step['stride'], 0)
            if off == count or stride < 2 or not 0 < stride * int(hit['bound'], 0) <= 0x7fffffff:
                continue
            if not re.search(rf'\baddiu\s+(\$\w+),\s*\1,\s*(?:{stride}|0[xX]{stride:x})\b', target, re.I):
                continue
            tick = re.search(_increment(count, '1'), body)
            if not tick or tick.start() > step.start() or len(re.findall(_increment(count, '1'), body)) != 1:
                continue
            dirty = rf'(?:&\s*{off}\b|\b{off}\s*(?:\+\+|--|(?:[-*/%&|^]|<<|>>)=|=(?!=)))'
            if len(re.findall(rf'\b{off}\s*(?:\+=|=\s*{off}\s*\+)', body)) != 1 or re.search(
                    dirty, body[:step.start()] + body[step.end():]):
                continue
            # every use must come before the counter ticks (after it the counter is one too far)
            if re.search(rf'\b{off}\b', body[tick.end():step.start()]) or re.search(rf'\b{off}\b', body[step.end():]):
                continue
            inits = re.search(rf'((?:\b{ID}\s*=\s*{NUM}\s*;\s*)+)$', clean[start:hit.start()])
            if not inits or not all(re.search(rf'\b{v}\s*=\s*0\s*;', inits[1]) for v in (count, off)):
                continue
            after = clean[hit.end():end]
            drop = None
            if re.search(rf'\b{off}\b', after):
                uses = list(re.finditer(rf'\b(?P<callee>{ID})\s*\(\s*{off}\s*\)', after))
                if len(re.findall(rf'\b{off}\b', after)) != len(uses) or not uses or any(
                        not re.search(rf'\b{u["callee"]}\s*\(\s*\)\s*;', clean) for u in uses):
                    continue
                drop = uses
            return [(COUNTER_STRIDE, _inline(source, hit, body, step, tick, off, count, stride, drop, end))]
    return []


def _inline(source, hit, body, step, tick, off, count, stride, drop, end):
    base = hit.start('body')
    new_body = body[:step.start()] + body[step.end():]
    new_body = re.sub(rf'\b{off}\b', f'({count} * {hex(stride).upper().replace("X", "x")})', new_body)
    text = source[:base] + new_body + source[hit.end('body'):]
    shift = len(new_body) - len(body)
    for use in reversed(drop or []):
        a, b = hit.end() + shift + use.start(), hit.end() + shift + use.end()
        text = text[:a] + use['callee'] + '()' + text[b:]
    head = text[:hit.start()]
    zero = list(re.finditer(rf'[ \t]*\b{off}\s*=\s*0\s*;[ \t]*\n?', head))[-1]
    head = head[:zero.start()] + head[zero.end():]
    return re.sub(rf'\n[ \t]*(?:s32|u32|int)\s+{off}\s*;[ \t]*(?=\n)', '', head + text[hit.start():], count=1)


def _statements(clean, start, end):
    """(begin, end) of each top-level statement in clean[start:end]; a braced block is one statement."""
    out, begin, depth, parens, pos = [], None, 0, 0, start
    while pos < end:
        ch = clean[pos]
        if begin is None and not ch.isspace():
            begin = pos
        if ch == '(':
            parens += 1
        elif ch == ')':
            parens -= 1
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and not re.match(r'\s*(?:else|while)\b', clean[pos + 1:end]):
                out.append((begin, pos + 1))
                begin = None
        elif ch == ';' and depth == 0 and parens == 0:
            out.append((begin, pos + 1))
            begin = None
        pos += 1
    return out


def _has_call(text):
    return any(m[1] not in KEYWORDS for m in re.finditer(rf'(?<![\w)\]])\b({ID})\s*\(', text))


def call_window_global_local(source, name):
    """A global pointer read repeatedly between two calls, held in a local from just after the first call."""
    if not (found := _function(source, name)):
        return []
    clean, start, end = found
    pointers = {m['g']: re.sub(r'\s*(\*+)$', r' \1', m['type'].strip()) for m in re.finditer(
        rf'\bextern\s+(?P<type>[A-Za-z_][\w \t]*?\*)\s*(?P<g>{ID})\s*;', clean) if 'volatile' not in m['type']}
    if not pointers or '__repair_gptr' in clean:
        return []
    statements = _statements(clean, start + 1, end - 1)
    calls = [i for i, (a, b) in enumerate(statements) if _has_call(clean[a:b]) and '{' not in clean[a:b]]
    found_variants = []
    for first, second in zip(calls, calls[1:] + [len(statements)]):
        window = statements[first + 1:second + 1 if second < len(statements) else second]
        if not window or any('{' in clean[a:b] for a, b in window):
            continue
        for g, kind in pointers.items():
            uses = [len(re.findall(rf'\b{g}\b', clean[a:b])) for a, b in window]
            if sum(uses) < 2 or sum(1 for n in uses if n) < 2:
                continue
            if any(re.search(rf'&\s*{g}\b|\b{g}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean[a:b]) for a, b in window):
                continue
            found_variants.append((sum(uses), g, kind, first, window))
    found_variants.sort(key=lambda item: -item[0])
    result = []
    for _, g, kind, first, window in found_variants[:4]:
        local = f'__repair_gptr{len(result)}'
        text = source
        for a, b in reversed(window):
            text = text[:a] + re.sub(rf'\b{g}\b', local, text[a:b]) + text[b:]
        at = statements[first][1]
        text = text[:at] + f'\n    {local} = {g};' + text[at:]
        text = text[:start + 1] + f'\n    {kind}{local};' + text[start + 1:]
        result.append((CALL_WINDOW, text))
    return result


def staged_float_constant(source, name):
    """A float literal stored in a loop, staged through a local where it stood and stored after the next temporary."""
    if not (found := _function(source, name)):
        return []
    clean, start, end = found
    if '__repair_fconst' in clean:
        return []
    loop = re.compile(r'\bdo\s*{(?P<body>[^{}]*)}\s*while\s*\(')
    result = []
    for hit in loop.finditer(clean, start, end):
        statements = _statements(clean, hit.start('body'), hit.end('body'))
        for i, (a, b) in enumerate(statements):
            store = re.match(r'(?P<lhs>.*?\))\s*=\s*(?P<lit>-?\d+\.\d*f)\s*;$', clean[a:b], re.S)
            if not store or float(store['lit'].rstrip('f')) == 0.0 or '*' not in store['lhs']:
                continue
            if any(re.search(re.escape(store['lit']), clean[x:y]) for x, y in statements[:i]):
                continue
            later = next((j for j in range(i + 1, len(statements))
                          if re.match(rf'{ID}\s*=\s*[^=]', clean[statements[j][0]:statements[j][1]])
                          and not re.match(rf'{ID}\s*=\s*{ID}\s*;', clean[statements[j][0]:statements[j][1]])), None)
            if later is None:
                continue
            local = f'__repair_fconst{len(result) // 3}'
            moved = f'{store["lhs"]} = {local};'
            staged_here = f'{local} = {store["lit"]};'
            plain = f'{store["lhs"]} = {store["lit"]};'
            sink_at = statements[later][1]
            for label, here, there in (('stage+sink', staged_here, moved), ('sink', '', plain), ('stage', staged_here + '\n        ' + moved, '')):
                text = source[:sink_at] + (('\n        ' + there) if there else '') + source[sink_at:]
                text = text[:a] + here + text[b:]
                if label != 'sink':
                    text = text[:start + 1] + f'\n    f32 {local};' + text[start + 1:]
                result.append((STAGED_FLOAT, text))
            if len(result) >= 12:
                return result
    return result


def variants(source, name, arch='mips', asm=''):
    """Every rewrite of this module for `source`: (family, child)."""
    return (counter_stride_inline(source, name, arch, asm) + call_window_global_local(source, name)
            + staged_float_constant(source, name))
