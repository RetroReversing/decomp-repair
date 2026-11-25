"""m2c's index temporaries for one call written back into it, and the record they index read through a typed pointer.

A triangle's three vertices passed to one call (`f(&plane, verts + tri[0] * 12, verts + tri[1] * 12, verts +
tri[2] * 12)`) come back from m2c as temporaries computed in scheduled order, one scale split across two of them, and
the record's address repeated in each:

    a2 = (*((u16 *) (((char *) (BASE)) + 2))) * 3; v0 = *((u16 *) (((char *) (BASE)) + 4)); a1 = F + ((*((u16 *) (((char *) (BASE)) + 0))) * 0xC);
    f(&plane, a1, F + (a2 * 4), F + (v0 * 0xC));

Compiled as written, the reads come in the temporaries' order and `* 3` then `* 4` is two scalings. The child puts each
temporary back into its one use in the call (`(X * 3) * 4` folded to `X * 0xC`) and reads the repeated record through
one pointer (`tri = (u16 *) (BASE); f(&plane, F + (tri[0] * 0xC), F + (tri[1] * 0xC), F + (tri[2] * 0xC));`).
A 1928-instruction collision sweep (KMC gcc 2.7.2): 17437 -> 16757, in two arms (u16 and u8 indices) at once; the
fold alone was worse (19047). One function; the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'call_index_temps_pointer'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
SIZE = {'u8': 1, 's8': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4}


def _python_expr_end(text, start):
    """Index of the `;` ending the expression that starts at `start` (top level)."""
    depth = 0
    for k in range(start, len(text)):
        c = text[k]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == ';' and depth == 0:
            return k
    return -1


_expr_end = _python_expr_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _expr_end(text, start):
        found = _scan.statement_end(text, start, len(text), '([', ')]', False, False, -1)
        return _python_expr_end(text, start) if found is NotImplemented else found


def _assignments(line):
    """`a = E; b = F;` on one line: [(name, expr)], or None."""
    out, k = [], 0
    while True:
        m = re.compile(r'\s*(' + I + r')\s*=(?!=)\s*').match(line, k)
        if not m:
            break
        end = _expr_end(line, m.end())
        if end < 0:
            return None
        out.append((m[1], line[m.end():end].strip()))
        k = end + 1
    return out if out and not line[k:].strip() else None


def _record_reads(text):
    """`*((T *) (((char *) (B)) + C))` reads: list of (match span, T, B, C)."""
    out = []
    for m in re.finditer(r'\*\(\(\s*(u8|s8|u16|s16|u32|s32)\s*\*\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*\(', text):
        base_open = m.end() - 1
        depth = 0
        for k in range(base_open, len(text)):
            if text[k] == '(':
                depth += 1
            elif text[k] == ')':
                depth -= 1
                if depth == 0:
                    break
        tail = re.compile(r'\s*\)\s*\+\s*(0x[0-9A-Fa-f]+|\d+)\s*\)\s*\)').match(text, k + 1)
        if not tail:
            continue
        out.append(((m.start(), tail.end()), m[1], text[base_open + 1:k], int(tail[1], 0)))
    return out


def _rewrite(lines, i, names, rest=''):
    """Lines i (temporaries) and i+1 (the call) rewritten, or None; `rest` is the code after them."""
    temps = _assignments(lines[i])
    call = lines[i + 1]
    if not temps or len(temps) < 2 or not re.fullmatch(r'\s*' + I + r'\s*\(.*\)\s*;\s*', call):
        return None
    for name, expr in temps:
        uses = len(re.findall(r'\b' + name + r'\b', call))
        if uses != 1 or any(re.search(r'\b' + name + r'\b', e) for _, e in temps):
            return None
        later = re.search(r'\b' + name + r'\b', rest)
        if later and not re.match(r'\s*=(?!=)', rest[later.end():]):
            return None  # read again before it is set again
        scaled = re.fullmatch(r'(.*\S)\s*\*\s*(0x[0-9A-Fa-f]+|\d+)', expr)
        use = re.search(r'\(\s*' + name + r'\s*\*\s*(0x[0-9A-Fa-f]+|\d+)\s*\)', call)
        if scaled and use:
            factor = int(scaled[2], 0) * int(use[1], 0)
            call = call[:use.start()] + '(%s * 0x%X)' % (scaled[1], factor) + call[use.end():]
        else:
            spelled = expr if re.fullmatch(I, expr) else '(' + expr + ')'
            call = re.sub(r'\b' + name + r'\b', lambda _, text=spelled: text, call)
    reads = _record_reads(call)
    groups = {}
    for span, kind, base, offset in reads:
        groups.setdefault((kind, base), []).append((span, offset))
    best = max(groups.items(), key=lambda kv: len(kv[1]), default=None)
    indent = re.match(r'[ \t]*', lines[i])[0]
    if not best or len(best[1]) < 2:
        return None
    (kind, base), items = best
    pointer = 'record_%s' % kind
    n = 2
    while pointer in names:
        pointer = 'record_%s_%d' % (kind, n)
        n += 1
    for span, offset in sorted(items, reverse=True):
        if offset % SIZE[kind]:
            return None
        call = call[:span[0]] + '%s[%d]' % (pointer, offset // SIZE[kind]) + call[span[1]:]
    call = re.sub(r'\(\s*(' + re.escape(pointer) + r'\[\d+\])\s*\)', r'\1', call)
    return [indent + '%s = (%s *) (%s);' % (pointer, kind, base), indent + call.lstrip()], (kind, pointer)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    head = source[:opening + 1]
    body = source[opening + 1:span[1]]
    lines = body.split('\n')
    names = set(re.findall(r'\b' + I + r'\b', clean))
    out_lines, decls, changed, k = [], [], 0, 0
    while k < len(lines):
        new = _rewrite(lines, k, names, '\n'.join(lines[k + 2:])) if k + 1 < len(lines) else None
        if new:
            replaced, decl = new
            out_lines += replaced
            if decl:
                names.add(decl[1])
                decls.append('  %s *%s;' % decl)
            changed += 1
            k += 2
            continue
        out_lines.append(lines[k])
        k += 1
    if not changed:
        return []
    text = head + ('\n' + '\n'.join(decls) if decls else '') + '\n'.join(out_lines) + source[span[1]:]
    return [(FAMILY, text)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
