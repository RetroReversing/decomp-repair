"""A guarded counting loop's invariants given to locals that earlier parts of the function used, as one child.

From a 207-instruction N64 text-layout function (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`), saved best 15: a
sentence loop's 0/1 flag took `$a1` where the target has `$a2` (the character copy beside it then took `$a2`), because
global.c gives the flag (12 weighted references over 13 insns) a register before the copy (9 over 23) and, in its first
pass, `find_reg` skips only the registers that LOWER-priority pseudos conflicting with it prefer (`prune_preferences`,
`regs_someone_prefers`). Nothing in that loop prefers `$a1`, so the flag took the lowest free register. The game's own
variables can carry the conflict in from the function's last loop, the one that scales every object of a table:

* the flag's variable also holds the truncated scale, `flag = (s32) scale;` before the `do` (the loop's
  `(s16) (s32) scale` store reads it). One pseudo, it now lives in the scale loop too, where it conflicts with the bound;
* the bound is a copy kept in the variable of the previous loop's line-start pointer (an `s32` there, read through a
  cast): `start = count;` before the `do`, `while (i < start)`. That variable is copied into `$a1` for a call
  (`memcpy(buf, start, n)`), so the bound prefers `$a1`, and the flag, which conflicts with it, avoids `$a1`;
* the count the bound copies is the previous loop's line counter (`n = (s16) G;` in place of `s16 count = G;`): the
  counter conflicts with the start pointer in that loop, so global.c's `expand_preferences` does not give the copy's
  preferences to the count, which would take `$a1` itself (the target has it in `$a0`: 15 -> 325 without this step);
* the float constant the loop divides by is set in a local after the truncation and before the bound's copy: loop.c
  puts the hoisted constant after every statement written before the `do`, and the first scheduler keeps the order of
  equal-priority insns, so the target's `lui; mtc1` before `move $a1,$a0` needs the constant written first (60 -> 0).

Each step alone is no better (the flag's merge alone gave the merged pseudo `$a1`: 15 -> 55; with the bound 325; with
the count 60), so they are one child. When the flag's variable is also named for a value after its own loop (an earlier
merge), that later web gets a fresh local first. The allocation and loop rules are read in global.c and loop.c; that the
game was written this way is a hypothesis the exact judge decides. The constant local is scaffolding.
"""
import re

FAMILY = 'loop_preheader_role_reuse'
FAMILIES = (FAMILY,)
LIMIT = 12
ID = r'[A-Za-z_]\w*'
WORD = {'s32', 'int', 'signed int', 'long'}
HALF = {'s16': 's16', 'short': 's16', 'u16': 'u16'}
DECL = re.compile(rf'^(?P<indent>[ \t]*)(?P<type>(?:unsigned\s+|signed\s+)?{ID})\s*(?P<stars>\**)\s*(?P<name>{ID})\s*;[ \t]*\n',
                  re.M)
FLOAT = re.compile(r'(?<![\w.])(?P<k>\d+\.\d*f)\b')
NOT_TYPES = {'return', 'goto', 'break', 'continue', 'else', 'do'}


def _blank(text):
    """Comments and string/char literals as spaces of the same length, so offsets stay the source's."""
    out, i = [], 0
    while i < len(text):
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = len(text) if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', text[i:j]))
            i = j
        elif text.startswith('//', i):
            j = text.find('\n', i)
            j = len(text) if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif text[i] in '"\'':
            q, j = text[i], i + 1
            while j < len(text) and text[j] != q:
                j += 2 if text[j] == '\\' else 1
            j = min(j + 1, len(text))
            out.append(' ' * (j - i))
            i = j
        else:
            out.append(text[i])
            i += 1
    return ''.join(out)


def _python_close(clean, at, a='{', b='}'):
    depth = 0
    for i in range(at, len(clean)):
        depth += (clean[i] == a) - (clean[i] == b)
        if depth == 0:
            return i
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(clean, at, a='{', b='}'):
        found = _scan.close_every(clean, at, a, b, False, None)
        return _python_close(clean, at, a, b) if found is NotImplemented else found


def _body(source, name):
    clean = _blank(source)
    for m in re.finditer(rf'\b{re.escape(name)}\s*\(', clean):
        paren = _close(clean, m.end() - 1, '(', ')')
        brace = paren is not None and re.match(r'\s*{', clean[paren + 1:])
        if brace:
            opening = paren + brace.end()
            closing = _close(clean, opening)
            if closing is not None:
                return clean, opening, closing
    return None


def _mentions(clean, name, start, end):
    """Offsets of `name` used as a variable between `start` and `end` (not a label, member or goto target)."""
    return [start + m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[start:end])
            if not re.match(r'\s*:(?!:)', clean[start + m.end():])
            and not re.search(r'\bgoto\s*$', clean[:start + m.start()])]


def _loops(clean, opening, closing):
    """(start, end) of every loop: `do {..} while (..);`, `for (..) {..}` and `while (..) {..}`."""
    spans = []
    for m in re.finditer(r'\b(do|for|while)\b', clean[opening:closing]):
        at = opening + m.start()
        if m[1] == 'do':
            brace = re.match(r'\s*{', clean[at + 2:])
            end = brace and _close(clean, at + 2 + brace.end() - 1)
            tail = end and re.match(r'\s*while\s*\(', clean[end + 1:])
            if tail:
                paren = _close(clean, end + 1 + tail.end() - 1, '(', ')')
                spans.append((at, (paren or end) + 1))
            continue
        if re.search(r'}\s*$', clean[opening:at]):
            continue  # a do-while's own `while`
        paren = re.match(r'\s*\(', clean[at + len(m[1]):])
        shut = paren and _close(clean, at + len(m[1]) + paren.end() - 1, '(', ')')
        brace = shut and re.match(r'\s*{', clean[shut + 1:])
        if brace:
            spans.append((at, (_close(clean, shut + brace.end()) or closing) + 1))
    return spans


def _bare_argument(clean, name, start, end):
    """Whether `name` is passed whole to a call between `start` and `end` (copied into an argument register)."""
    return re.search(rf'\b{ID}\s*\((?:[^;()]*,)?\s*{re.escape(name)}\s*[,)]', clean[start:end]) is not None


def _apply(source, edits):
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _child(source, clean, closing, decls, loop, start_name, counter, flag, later):
    do_at, bound, bound_at, scaled, cast, constant, indent = loop
    edits = []
    taken = set(re.findall(ID, clean))
    if later:
        fresh = flag + '_late'
        while fresh in taken:
            fresh += '_'
        taken.add(fresh)
        d = decls[flag]
        edits.append((d.end(), d.end(), f"{d['indent']}{d['type']} {fresh};\n"))
        edits += [(h, h + len(flag), fresh) for h in later]
    s = decls[start_name]
    if s['stars']:
        ptype = f"{s['type']} {s['stars']}"
        edits.append((s.start('type'), s.end('name'), f"s32 {start_name}"))
        for h in _mentions(clean, start_name, s.end(), closing):
            assign = re.match(rf'{re.escape(start_name)}\s*=(?!=)\s*(?P<rhs>[^;]+);', clean[h:])
            if assign:
                edits.append((h + assign.start('rhs'), h + assign.end('rhs'),
                              f"(s32) {source[h + assign.start('rhs'):h + assign.end('rhs')]}"))
            else:
                edits.append((h, h + len(start_name), f"(({ptype}) {start_name})"))
    count = bound
    if counter:
        count = counter
        b = decls[bound]
        edits.append((b.start(), b.end(), ''))
        for h in _mentions(clean, bound, b.end(), closing):
            if h == bound_at:
                continue
            edits.append((h, h + len(bound), counter))
            assign = re.match(rf'{re.escape(bound)}\s*=(?!=)\s*(?P<rhs>[^;]+);', clean[h:])
            if assign and b['type'] in HALF:
                edits.append((h + assign.start('rhs'), h + assign.end('rhs'),
                              f"({HALF[b['type']]}) {source[h + assign.start('rhs'):h + assign.end('rhs')]}"))
    pre = f"{flag} = (s32) {scaled};\n{indent}"
    if constant:
        k = 'scale'
        while k in taken:
            k += '_'
        pre += f"{k} = {constant['k']};\n{indent}"
        d = decls[scaled]
        edits.append((d.end(), d.end(), f"{d['indent']}f32 {k};\n"))
        at = do_at + constant.start('k')
        edits.append((at, at + len(constant['k']), k))
    pre += f"{start_name} = {count};\n{indent}"
    edits.append((do_at, do_at, pre))
    edits.append((do_at + cast.start(), do_at + cast.end(), flag))
    edits.append((bound_at, bound_at + len(bound), start_name))
    return _apply(source, edits)


def variants(source, name):
    found = _body(source, name)
    if not found:
        return []
    clean, opening, closing = found
    decls = {}
    for d in DECL.finditer(clean, opening + 1, closing):
        if d['type'] not in NOT_TYPES and d['name'] not in decls:
            decls[d['name']] = d
    loops = _loops(clean, opening, closing)
    out = []
    for m in re.finditer(r'\bdo\s*{', clean[opening:closing]):
        do_at = opening + m.start()
        body_end = _close(clean, opening + m.end() - 1)
        tail = body_end and re.match(rf'\s*while\s*\(\s*{ID}(?:\.{ID})?\s*<\s*(?P<b>{ID})\s*\)\s*;', clean[body_end + 1:])
        if not tail or tail['b'] not in decls:
            continue
        bound = tail['b']
        bound_at = body_end + 1 + tail.start('b')
        text = clean[do_at:body_end]
        cast = re.search(rf'\(\s*\(\s*s32\s*\)\s*(?P<x>{ID})\s*\)|\(\s*s32\s*\)\s*(?P<y>{ID})\b', text)
        scaled = cast and (cast['x'] or cast['y'])
        if not scaled or scaled not in decls or decls[scaled]['type'] != 'f32' or decls[scaled]['stars']:
            continue
        if re.search(rf'(?<![\w.>]){re.escape(scaled)}\s*=(?!=)', text):
            continue  # not invariant
        hits = _mentions(clean, bound, decls[bound].end(), closing)
        guard = clean.rfind('if', opening, do_at)
        if not hits or guard < 0:
            continue
        region = min(hits[0], guard)
        loop = (do_at, bound, bound_at, scaled, cast, FLOAT.search(text), re.search(r'([ \t]*)$', source[:do_at])[1])

        def uses(local):
            return _mentions(clean, local, decls[local].end(), closing)

        starts = [n for n, d in decls.items() if n not in (bound, scaled) and (d['stars'] or d['type'] in WORD)
                  and uses(n) and uses(n)[-1] < region and _bare_argument(clean, n, opening, region)]
        starts.sort(key=lambda n: (not decls[n]['stars'], -uses(n)[-1]))  # a pointer argument first
        word_bound = decls[bound]['type'] in WORD and not decls[bound]['stars']
        flags = []
        for n, d in decls.items():
            if d['type'] not in WORD or d['stars'] or n == bound:
                continue
            own = uses(n)
            home = next(((s, e) for s, e in loops if own and s <= own[0] < e), None)
            if home and home[1] <= region and re.search(rf'(?<![\w.>]){re.escape(n)}\s*=\s*1\s*;', clean[home[0]:home[1]]):
                flags.append((n, [h for h in own if h > home[1]]))
        for start_name in starts[:2]:
            s_hits = uses(start_name)
            counters = [None] if word_bound else [
                n for n, d in decls.items() if d['type'] in WORD and not d['stars'] and n not in (bound, start_name)
                and uses(n) and uses(n)[-1] < hits[0] and uses(n)[0] < s_hits[-1] and uses(n)[-1] > s_hits[0]]
            # a counter first (`++n`, `n++`, `n += 1`): the line count lives beside the start pointer
            counters.sort(key=lambda n: n is not None and not re.search(
                rf'\+\+\s*{re.escape(n)}\b|(?<![\w.>]){re.escape(n)}\s*(?:\+\+|\+=\s*1\b)', clean[opening:closing]))
            for counter in counters[:2]:
                for flag, later in flags[:3]:
                    if flag in (counter, start_name):
                        continue
                    child = _child(source, clean, closing, decls, loop, start_name, counter, flag, later)
                    if child != source and all(child != t for _, t in out):
                        out.append((FAMILY, child))
                    if len(out) >= LIMIT:
                        return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
