"""A global pointer read at several separate statements, read at each into one shared local (`g = G;` before each
statement, which then uses `g`), optionally with the first statements of one site in a one-shot scope.

On a 231-instruction N64 loader (SN64 GCC 2.8.1, `sn-n64-281 -G0 -mips3 -O2 ... -mfp32`) the source read a record
pointer global twice, `G->C0 = 2;` before a call and `G->D8 = G->9C;` inside a loop, and the copy came out with the
pointer and the value in each other's registers (`lw $v1, 0x9c($v0); sw $v1, 0xd8($v0)` where the target has
`lw $v0, 0x9c($v1); sw $v0, 0xd8($v1)`). Read straight from the global, each read is a pseudo of its own block, and
local-alloc.c gives the pointer (three references) the first free register before the value. One local assigned at
both sites is set in two blocks, so global.c allocates it after every block-local quantity: the value takes `$v0` and
the pointer `$v1`, as in the target. The shared local then ranked just below the loop's record pointer (3.429 against
3.538, `floor_log2 (refs) * refs / live_length`); one more weighted reference, from a `do { } while (0);` around the
first site together with the call before it and the call after it, put it first (7510 -> 0). Wrapping the global's
load inside the loop instead raised the loop-hoisted `%hi` of the global as well and swapped two saved registers;
wrapping only the first site's two statements cut the scheduler's region and moved an argument copy.

global_pointer_site_local
    One child with every site (up to four) read through the shared local, then, for each site, the same with the site
    (its `g = G;` and its statement) in a one-shot scope, alone, with the plain statement after it, with the one before
    it, and with both. Statements that are not plain one-line statements (`break`, `return`, control headers,
    declarations) never go into a scope.

Hypothesis from that match (local-alloc.c and global.c's order, flow.c's loop-depth weights); the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'global_pointer_site_local'
FAMILIES = (FAMILY,)
MAX_SITES = 4
_EXTERN = re.compile(rf'\bextern\s+(?P<type>(?:(?:const|volatile|unsigned|signed|struct)\s+)*{IDENT}\s*\*+)\s*'
                     rf'(?P<name>{IDENT})\s*;')
_KEYWORD = re.compile(r'^\s*(?:if|for|while|do|switch|return|break|continue|goto|case|default|else)\b')
_DECLARATION = re.compile(rf'^\s*(?:(?:static|register|const|volatile|unsigned|signed|struct)\s+)*{IDENT}[\s*]+'
                          rf'{IDENT}\s*(?:=|;|\[|,)')


def _pointer_globals(source, header):
    found = {}
    for text in (header or '', source):
        for hit in _EXTERN.finditer(text):
            found[hit['name']] = re.sub(r'\s*(\*+)$', r' \1', hit['type'].strip())
    return found


def _lines(source, part):
    """(start, end, indent, clean text) of every line of the function's body."""
    out, at = [], part.opening + 1
    for line in source[part.opening + 1:part.end].splitlines(keepends=True):
        start, at = at, at + len(line)
        end = start + len(line.rstrip('\r\n'))
        out.append((start, end, line[:len(line) - len(line.lstrip())], part.clean[start:end]))
    return out


def _plain(clean_line, before):
    """A one-line statement that may go into a one-shot scope: it starts a statement and ends it on its own line."""
    text = clean_line.strip()
    return (text.endswith(';') and before[-1:] in (';', '{', '}') and not _KEYWORD.match(text)
            and not _DECLARATION.match(text) and not re.search(r'[{}]', text)
            and not re.search(r'\b(?:break|continue|return|goto)\b', text))


def _reads(clean_line, symbol):
    hits = list(re.finditer(rf'(?<![\w.&]){re.escape(symbol)}\b', clean_line))
    if not hits or any(re.match(r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean_line[h.end():]) for h in hits):
        return []
    return [(h.start(), h.end()) for h in hits]


def _local_name(clean, symbol):
    base = 'p' + re.sub(r'^[A-Za-z]_', '', symbol)
    name, n = base, 2
    while re.search(rf'\b{re.escape(name)}\b', clean):
        name, n = f'{base}_{n}', n + 1
    return name


def _site_text(source, line, spans, symbol, local):
    start, end, indent, _ = line
    text, pos, pieces = source[start:end].strip(), 0, []
    offset = start + (len(source[start:end]) - len(source[start:end].lstrip()))
    for a, b in spans:
        pieces += [text[pos:a + start - offset], local]
        pos = b + start - offset
    pieces.append(text[pos:])
    return [f'{local} = {symbol};', ''.join(pieces)]


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    lines = _lines(source, part)
    out = []
    for symbol, ctype in _pointer_globals(source, header).items():
        sites = []
        for i, line in enumerate(lines):
            before = clean[:line[0]].rstrip()
            spans = _reads(line[3], symbol)
            if spans and _plain(line[3], before):
                sites.append((i, [(line[0] + a, line[0] + b) for a, b in spans]))
        if len(sites) < 2:
            continue
        sites = sites[:MAX_SITES]
        site_rows = {i for i, _ in sites}
        local = _local_name(clean, symbol)
        first = next((ln for ln in lines if ln[3].strip()), None)
        indent = first[2] if first else '    '
        declaration = (part.opening + 1, part.opening + 1, f'\n{indent}{ctype}{local};'
                       if ctype.endswith('*') else f'\n{indent}{ctype} {local};')

        def body(i, spans, symbol=symbol, local=local):
            return _site_text(source, lines[i], [(a - lines[i][0], b - lines[i][0]) for a, b in spans], symbol, local)

        plain = [declaration] + [(lines[i][0], lines[i][1], '\n'.join(lines[i][2] + t for t in body(i, spans)))
                                 for i, spans in sites]
        out.append((FAMILY, edit(source, plain)))

        def neighbour(i, step, site_rows=site_rows):
            j = i + step
            if not 0 <= j < len(lines) or j in site_rows or lines[j][2] != lines[i][2]:
                return None
            before = clean[:lines[j][0]].rstrip()
            return j if _plain(lines[j][3], before) else None

        for i, spans in sites:
            prev, nxt = neighbour(i, -1), neighbour(i, 1)
            for p, n in dict.fromkeys(((None, None), (None, nxt), (prev, None), (prev, nxt))):
                pad = lines[i][2]
                inner = ([source[lines[p][0]:lines[p][1]].strip()] if p is not None else []) + body(i, spans) + \
                        ([source[lines[n][0]:lines[n][1]].strip()] if n is not None else [])
                scoped = f'{pad}do {{\n' + ''.join(f'{pad}    {t}\n' for t in inner) + f'{pad}}} while (0);'
                lo = lines[p][0] if p is not None else lines[i][0]
                hi = lines[n][1] if n is not None else lines[i][1]
                edits = [declaration, (lo, hi, scoped)]
                edits += [(lines[k][0], lines[k][1], '\n'.join(lines[k][2] + t for t in body(k, s)))
                          for k, s in sites if k != i]
                child = edit(source, edits)
                if all(child != text for _, text in out):
                    out.append((FAMILY, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
