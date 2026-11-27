"""A nested row loop (an exchange sort of fixed-size records) written the way the game wrote it: parameters held in
locals, and the rotated goto loop as a plain `while`.

m2c reads a compare-and-swap row sort as a guarded, label-and-goto loop that works on its parameters directly:

    V = 0;  if (n > 0) { j = n - 1;  L: { ...  V += 1;  j = n - 1; }  if (V < n) goto L; }

The game's version is `n = arg1; stride = arg2; cmp = arg3; base = arg0;` then `while (V < n) { j = n - 1; ... }` over
those copies, and the frame carries fewer pad words than the draft's (`s32 pad[2]` for `pad[4]`). Measured on an SN GCC
2.7.2 (`-G0 -mips3 -O1 -mgp32 -mhard-float`) 60-instruction N64 sort-by-callback routine (20 -> 0): the copies and the
`while` loop together; each alone stays at 20.

Two families, both candidates the exact judge decides:
- `row_loop_while`: `V = 0; if (N > 0) { PRE; L: { BODY PRE; } if (V < N) goto L; }`, where PRE is one assignment that
  ends the body again, becomes `V = 0; while (V < N) { PRE; BODY }`.
- `param_copies`: every parameter the body uses (two or more parameters, a loop present, none assigned or address-taken)
  gets a local copy set at the head and used instead. A declared `pad[N]` array also gets children with two fewer words
  and half as many (the copies take saved registers the draft's pad had been standing in for).
"""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, edit, view

WHILE = 'row_loop_while'
COPIES = 'param_copies'
FAMILIES = (WHILE, COPIES)

HEAD = re.compile(
    rf'(?P<set>(?<![\w.])(?P<v>{IDENT})\s*=\s*0\s*;)\s*'
    rf'if\s*\(\s*(?P<n>{IDENT})\s*>\s*0\s*\)\s*\{{\s*(?P<pre>{IDENT}\s*=[^;{{}}]+;)\s*'
    rf'(?P<label>{IDENT})\s*:\s*\{{')
DECLARATION = re.compile(rf'\A(?:(?:unsigned|signed|const|volatile|struct)\s+)*{IDENT}(?:\s+{IDENT})*\s+[^=;()]*\s*;\Z')
PAD = re.compile(r'(?P<head>\bs32\s+pad\[)(?P<n>\d+)\]')


def _while(source, name, part):
    out = []
    pairs = brace_pairs(part.clean, part.opening, part.end) or {}
    clean = part.clean
    for hit in HEAD.finditer(clean, part.opening, part.end):
        opening = hit.end() - 1
        closing = pairs.get(opening)
        outer = pairs.get(clean.rfind('{', hit.start(), hit.start('pre')))
        if closing is None or outer is None:
            continue
        tail = re.match(rf'\s*if\s*\(\s*{hit["v"]}\s*<\s*{hit["n"]}\s*\)\s*goto\s+{hit["label"]}\s*;\s*', clean[closing + 1:])
        if not tail or clean[closing + 1 + tail.end():outer].strip():
            continue
        pre = hit['pre'].strip()
        body = clean[opening + 1:closing].rstrip()
        if not body.endswith(pre):
            continue
        body = source[opening + 1:closing].rstrip()
        body = body[:len(body) - len(pre)].rstrip()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start('set')) + 1:])[0]
        inside = [row[4:] if row.startswith(indent + ' ' * 8) else row for row in body.strip('\n').split('\n')]
        text = (f'{hit["set"]}\n{indent}while ({hit["v"]} < {hit["n"]}) {{\n{indent}    {pre}\n'
                + '\n'.join(inside) + f'\n{indent}}}')
        out.append((WHILE, edit(source, [(hit.start('set'), outer + 1, text)])))
    return out


def _parameters(clean, opening, name):
    head = re.search(rf'\b{re.escape(name)}\s*\(', clean[:opening])
    if not head:
        return []
    pieces, depth, begin = [], 0, head.end()
    for at in range(head.end(), clean.rfind(')', 0, opening)):
        char = clean[at]
        depth += (char == '(') - (char == ')')
        if char == ',' and depth == 0:
            pieces.append(clean[begin:at])
            begin = at + 1
    pieces.append(clean[begin:clean.rfind(')', 0, opening)])
    found = []
    for piece in pieces:
        piece = piece.strip()
        names = re.findall(IDENT, piece)
        if piece and piece != 'void' and names:
            found.append((piece, names[-1] if '(*' not in piece else re.search(rf'\(\*\s*({IDENT})\s*\)', piece)[1]))
    return found


def _copies(source, name, part):
    clean = part.clean
    body = clean[part.opening + 1:part.end - 1]
    if not re.search(r'\b(?:while|for|do|goto)\b', body):
        return []
    params = [(text, ident) for text, ident in _parameters(clean, part.opening, name)
              if re.search(rf'\b{ident}\b', body)]
    if len(params) < 2 or any(re.search(rf'(?<![\w.>&]){ident}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|&\s*{ident}\b|(?:\+\+|--)\s*{ident}\b|\b{ident}\s*(?:\+\+|--)', body)
                              for _, ident in params):
        return []
    units = statements(clean, part.opening + 1, part.end - 1)
    first = next((a for a, b in units if not DECLARATION.match(clean[a:b])), None)
    if first is None:
        return []
    names = {}
    for text, ident in params:
        fresh = f'{ident}_copy'
        if re.search(rf'\b{fresh}\b', clean):
            return []
        names[ident] = (fresh, re.sub(rf'\b{ident}\b', fresh, text))
    line = source.rfind('\n', 0, first) + 1
    indent = re.match(r'[ \t]*', source[line:])[0]
    decl_at = source.find('\n', part.opening) + 1
    declarations = ''.join(f'{indent}{decl};\n' for _, decl in names.values())
    sets = ''.join(f'{indent}{fresh} = {ident};\n' for ident, (fresh, _) in names.items())
    rename = [(first + m.start(), first + m.end(), names[m[0]][0]) for m in re.finditer(IDENT, clean[first:part.end - 1])
              if m[0] in names]
    # the declarations go after a leading `pad[...]` line if there is one, else at the head
    pad = re.match(r'[ \t]*s32\s+pad\[\d+\];\n', source[decl_at:])
    at = decl_at + (pad.end() if pad else 0)
    base = [(m_start, m_end, text) for m_start, m_end, text in rename]
    base += [(at, at, declarations), (line, line, sets)]
    out = [(COPIES, edit(source, base))]
    size = PAD.search(clean, part.opening, part.end)
    if size:
        for words in sorted({int(size['n']) - 2, int(size['n']) // 2} - {0, int(size['n'])}):
            if words > 0:
                text = edit(source, base + [(size.start('n'), size.end('n'), str(words))])
                out.append((COPIES, text))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    return _while(source, name, part) + _copies(source, name, part)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
