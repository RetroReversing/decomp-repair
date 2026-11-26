"""A one-line store or initialiser moved across the call beside it, in either direction, and a test's call taken out first.

GCC 2.x schedules a call as a barrier: a store or a register set on one side of a `jal` cannot move to the other, so
where the source puts a constant store (a flag cleared, a field zeroed, `var = 0;`) relative to a call is the code's
order, and so is how long the stored value's register lives. The existing moves go one way or are particular (`init_after_call`
puts `x = K;` after a call; `copy_sink_after_call_repairs` a copy; `constant_store_early_local` a store early).
Hand matches on N64 SN/KMC GCC code needed each direction by itself: a result variable cleared BEFORE the call and the
load that follows it (`var = 0; f(); t = o->mode;` where m2c wrote `f(); t = o->mode; var = 0;`), a field store AFTER a
call it was written before, and a call in a test taken into a local before the store that precedes the test
(`o->f64 = 0; if (r <= f(o, r)) {` as `v = f(o, r); o->f64 = 0; if (r <= v) {`).

Children (`LIMIT` in all, the condition's first, then in the source's order):
- `statement_hoist_over_call`: a simple assignment `x = K;` / `p->m = K;` (a numeric literal on the right) written above the one or two simple statements before it in its block, at least one of which holds a call and
  none of which names the assigned location or the value it reads;
- `statement_sink_past_call`: the same statement written below the one or two simple statements after it, the same way;
- `condition_call_before_store`: a simple assignment directly above an `if (...)` whose test holds exactly one call with a
  known non-void return type (from the header) and no `&&`, `||` or `?`: the call's result in a new local above the
  assignment, and the test reading the local.
A function with `volatile`, `asm`, `goto` or a preprocessor line is left alone. Proposals only; the byte judge decides."""
import re

from .integer_repair_support import IDENT, edit, view
from .local_split_reuse import _balanced, _insert_declaration, _return_type

FAMILY_HOIST = 'statement_hoist_over_call'
FAMILY_SINK = 'statement_sink_past_call'
FAMILY_CONDITION = 'condition_call_before_store'
FAMILIES = (FAMILY_HOIST, FAMILY_SINK, FAMILY_CONDITION)
LIMIT = 8
REACH = 2
_KEYWORDS = {'if', 'else', 'while', 'for', 'do', 'switch', 'return', 'goto', 'break', 'continue', 'case', 'default',
             'typedef', 'extern', 'static', 'register', 'sizeof', 'struct', 'union', 'enum'}
_CALL = re.compile(rf'(?<![\w.>])(?!(?:{"|".join(sorted(_KEYWORDS))})\b)(?P<callee>{IDENT})\s*\(')
_SIMPLE = re.compile(r'(?P<lhs>[^;{}=!<()]*(?:M2C_FIELD\s*\([^;{}=]*\)|\*\s*\([^;{}=]*\)[^;{}=]*)?[^;{}=!<()]*?)\s*=(?!=)\s*'
                     r'(?P<rhs>-?\s*(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?[fFuU]*))\s*;')


def _statements(clean, lo, hi):
    """[(start, end, kind)] of the statements directly inside the block [lo, hi): `simple` (ends at `;`, no braces) or
    `compound` (a statement with a block, its `else` chain included)."""
    out, at = [], lo
    while at < hi:
        while at < hi and clean[at] in ' \t\r\n':
            at += 1
        if at >= hi:
            break
        start = at
        depth, brace = 0, False
        while at < hi:
            char = clean[at]
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            elif char == '{' and depth == 0:
                brace = True
                level = 0
                while at < hi:
                    level += {'{': 1, '}': -1}.get(clean[at], 0)
                    at += 1
                    if level == 0:
                        break
                rest = clean[at:hi].lstrip()
                if rest.startswith('else'):
                    at = len(clean[:hi]) - len(rest) + 4
                    continue
                if re.match(r'\s*while\b', rest) and re.match(r'\s*do\b', clean[start:start + 8]):
                    at = clean.find(';', at) + 1
                break
            elif char == ';' and depth == 0:
                at += 1
                break
            at += 1
        out.append((start, at, 'compound' if brace or re.match(r'(?:if|for|while|switch|do)\b', clean[start:at]) else 'simple'))
    return out


def _python_blocks(clean, lo, hi):
    """The (open+1, close) of the function body and of every block in it."""
    stack, found = [], [(lo, hi - 1)]
    for at in range(lo, hi):
        if clean[at] == '{':
            stack.append(at)
        elif clean[at] == '}' and stack:
            found.append((stack.pop() + 1, at))
    return found


_blocks = _python_blocks
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _blocks(clean, lo, hi):
        found = _scan.block_pairs(clean, lo, hi)
        if found is not NotImplemented:
            return [(lo, hi - 1)] + [(opening + 1, closing) for opening, closing in found]
        return _python_blocks(clean, lo, hi)


def _line_span(source, start, end):
    """(from, to) to delete a statement: its whole line when it is alone on it, else just its text."""
    begin = source.rfind('\n', 0, start) + 1
    stop = source.find('\n', end)
    stop = len(source) if stop < 0 else stop
    if not source[begin:start].strip() and not source[end:stop].strip():
        return begin, min(stop + 1, len(source))
    return start, end


def _names(text):
    return {n for n in re.findall(IDENT, text) if n not in _KEYWORDS}


def _simple(clean, start, end):
    match = _SIMPLE.fullmatch(clean[start:end].strip())
    # a compound assignment (`count *= 8;`, `x >>= 1;`) reads its location: the left side then ends in the operator,
    # and moving it past a statement that reads the location changed the program (a call got `count`, not `count * 8`)
    if match and match['lhs'].rstrip()[-1:] in tuple('+-*/%&|^<>'):
        return None
    return match


def _has_call(clean, start, end):
    return bool(_CALL.search(clean[start:end].replace('M2C_FIELD', '')))


def _move_children(source, name, part):
    out = []
    clean = part.clean
    for lo, hi in _blocks(clean, part.opening + 1, part.end):
        items = _statements(clean, lo, hi)
        for index, (start, end, kind) in enumerate(items):
            match = kind == 'simple' and _simple(clean, start, end)
            if not match or _has_call(clean, start, end):
                continue
            for direction in (-1, 1):
                for reach in range(1, REACH + 1):
                    passed = items[index + direction * reach:index] if direction < 0 else items[index + 1:index + 1 + reach]
                    if len(passed) != reach or index + direction * reach < 0:
                        continue
                    if any(item[2] != 'simple' for item in passed) or not any(_has_call(clean, a, b) for a, b, _ in passed):
                        continue
                    between = re.sub(r'\s+', '', ''.join(clean[a:b] for a, b, _ in passed))
                    place = re.sub(r'\s+', '', match['lhs'])
                    plain = re.fullmatch(IDENT, place)
                    if re.search(rf'(?<![\w.>]){re.escape(place)}\b', between) if plain else place in between:
                        continue
                    text = source[start:end]
                    cut = _line_span(source, start, end)
                    indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
                    if direction < 0:
                        first = passed[0][0]
                        child = edit(source, [(*cut, ''), (source.rfind('\n', 0, first) + 1, source.rfind('\n', 0, first) + 1, indent + text + '\n')])
                        family = FAMILY_HOIST
                    else:
                        last = passed[-1][1]
                        child = edit(source, [(*cut, ''), (last, last, '\n' + indent + text)])
                        family = FAMILY_SINK
                    if view(child, name):
                        out.append((family, child))
    return out


def _condition_children(source, name, part, header):
    out = []
    clean = part.clean
    used = set(re.findall(IDENT, clean[part.opening:part.end]))
    for lo, hi in _blocks(clean, part.opening + 1, part.end):
        items = _statements(clean, lo, hi)
        for (start, end, kind), (nstart, nend, nkind) in zip(items, items[1:]):
            if kind != 'simple' or nkind != 'compound' or not _simple(clean, start, end) or _has_call(clean, start, end):
                continue
            head = re.match(r'if\s*\(', clean[nstart:nend])
            if not head:
                continue
            open_at = nstart + head.end() - 1
            close = _balanced(clean, open_at)
            if close < 0:
                continue
            test = clean[open_at + 1:close - 1]
            calls = list(_CALL.finditer(test))
            if len(calls) != 1 or re.search(r'&&|\|\||\?', test):
                continue
            callee = calls[0]['callee']
            kind_name = _return_type(header, callee)
            if not kind_name or kind_name.split()[-1] == 'void' and not kind_name.endswith('*'):
                continue
            stop = _balanced(clean, open_at + 1 + calls[0].end() - 1)
            if stop < 0:
                continue
            call_text = test[calls[0].start():stop - open_at - 1]
            local = f'call_{len(used)}'
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
            at = source.rfind('\n', 0, start) + 1
            child = edit(source, [(open_at + 1 + calls[0].start(), open_at + 1 + calls[0].start() + len(call_text), local),
                                  (at, at, f'{indent}{local} = {call_text};\n')])
            moved = view(child, name)
            if moved:
                declaration = f'{kind_name}{local};' if kind_name.endswith('*') else f'{kind_name} {local};'
                out.append((FAMILY_CONDITION, _insert_declaration(child, moved, declaration)))
                used.add(local)
    return out


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__|goto)\b|^\s*#', body, re.M):
        return []
    out = _condition_children(source, name, part, header) + _move_children(source, name, part)
    return list(dict.fromkeys(item for item in out if item[1] != source))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
