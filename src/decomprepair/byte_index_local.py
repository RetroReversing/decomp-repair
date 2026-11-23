"""A scaled slot index read by several array lookups, kept in a local set right after the slot's address locals.

`T[i * 4]` read three times (`D_800E076B[i * 4]`, `D_800E076A[i * 4]`, a halfword table at `i * 2`) is one `sll $a0,$a1,2`
that cse emits at the first of them, after the stores in between. The game's `sll` sat among the first insns of the
loop body, before its stores, and the first scheduler keeps the order insns were emitted in; a local that holds the
offset, `j = i * 4;` set right after the pointers the slot defines, emits it there. The local also gives the offset
references and a live range of its own (`global.c` orders pseudos by `floor_log2(refs) * refs / live length`), which
is what a later step has to weigh against the slot's own (`statement_scope_weight`). In a `gcc-2.7.2-kmc` save-slot
reset loop that was one of the four changes between the saved best (455) and the match, none worth anything alone
(`slot_loop_scaffold` offers them together).

Offered for a local `V` (a declaration with an initialiser, or a plain assignment as the first statement of its
block) with two or more subscripts `X[V * K]` or `X[V << n]` of one `K` (2, 4, 8 or 16) in the function, never assigned
again: one child with `T V_scaled = V * K;` after the run of initialised declarations (or simple assignments) that
follows `V`'s, and those subscripts reading it (`byte_index_local`). A hypothesis; the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import lines

FAMILY = 'byte_index_local'
FAMILIES = (FAMILY,)
LIMIT = 6
TYPE = rf'(?:(?:unsigned|signed|const|register)\s+)*{IDENT}'
DECL_INIT = re.compile(rf'^(?P<indent>[ \t]*)(?P<type>{TYPE})(?P<gap>[ \t]*\*+[ \t]*|[ \t]+)(?P<name>{IDENT})[ \t]*=[ \t]*(?P<init>[^;{{}}]+);[ \t]*$')
DECL_PLAIN = re.compile(rf'^(?P<indent>[ \t]*)(?P<type>{TYPE})(?P<gap>[ \t]*\*+[ \t]*|[ \t]+)(?P<name>{IDENT})[ \t]*;[ \t]*$')
ASSIGN = re.compile(rf'^(?P<indent>[ \t]*)(?P<name>{IDENT})[ \t]*=[ \t]*(?P<value>[^;{{}}]+);[ \t]*$')
CALL = re.compile(rf'(?<![(\w])(?!(?:s|u)(?:8|16|32|64)\b|int\b|char\b|short\b|long\b|unsigned\b)({IDENT})\s*\(')
KEYWORDS = {'return', 'if', 'else', 'for', 'while', 'do', 'switch', 'goto', 'break', 'continue', 'case', 'default'}
SCALED = re.compile(rf'\[\s*(?P<v>{IDENT})\s*(?:\*\s*(?P<k>\d+)|<<\s*(?P<n>\d+))\s*\]')


def _scale(match):
    k = int(match['k']) if match['k'] else 1 << int(match['n'])
    return k if k in (2, 4, 8, 16) else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    found = {}
    for hit in SCALED.finditer(part.clean, part.opening, part.end):
        k = _scale(hit)
        if k:
            found.setdefault((hit['v'], k), []).append(hit)
    out = []
    for (var, k), hits in found.items():
        if len(hits) < 2:
            continue
        assigns = len(re.findall(rf'(?<![\w.]){re.escape(var)}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|(?<![\w.])(?:\+\+|--)\s*{re.escape(var)}\b|\b{re.escape(var)}\s*(?:\+\+|--)',
                                 part.clean[part.opening:part.end]))
        at = decl_type = plain_decl = None
        for n, line in enumerate(body):
            m = DECL_INIT.match(line.text)
            if m and m['name'] == var and m['type'].split()[-1] not in KEYWORDS and assigns == 1:
                at, decl_type = n, m['type'].strip()
                break
            m = DECL_PLAIN.match(line.text)
            if m and m['name'] == var and assigns == 1:
                plain_decl, decl_type = n, m['type'].strip()
            m = ASSIGN.match(line.text)
            if m and m['name'] == var and plain_decl is not None and assigns == 1:
                at = n
                break
        if at is None or '*' in (decl_type or '*'):
            continue
        end = at
        while end + 1 < len(body):
            nxt = body[end + 1].text
            m = DECL_INIT.match(nxt) or ASSIGN.match(nxt)
            if not m or CALL.search(m.groupdict().get('init') or m.groupdict().get('value') or '') or (
                    m['name'] == var) or m['name'] in KEYWORDS:
                break
            end += 1
        scaled = f'{var}_scaled'
        if re.search(rf'\b{scaled}\b', part.clean):
            continue
        indent = re.match(r'[ \t]*', body[at].text)[0]
        edits = []
        if plain_decl is None:
            insert = f'{indent}{decl_type} {scaled} = {var} * {k};\n'
        else:
            insert = f'{indent}{scaled} = {var} * {k};\n'
            edits.append((body[plain_decl].end, body[plain_decl].end, f'{indent}{decl_type} {scaled};\n'))
        edits.append((body[end].end, body[end].end, insert))
        after = body[end].end
        for hit in hits:
            if hit.start() >= after:
                edits.append((hit.start(), hit.end(), f'[{scaled}]'))
        if sum(1 for hit in hits if hit.start() >= after) < 2:
            continue
        out.append((FAMILY, edit(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
