"""guard_tail_return_hoist: `if (C) { BODY } return V;` written as the early return `if (!C) { return V; } BODY return V;`.

Matched on a Nintendo 64 function built by SN-N64 2.81 (`-G0 -mips3 -mgp32 -mfp32 -O2`, 105 -> 0): a function that asks a
helper for a pointer and, only when it is NULL, makes one itself (two calls and some field stores), then returns the
pointer. m2c writes the test around the work:

    var_v0 = get(); if (var_v0 == NULL) { ...; var_s0 = make(); ...; var_v0 = var_s0; } return var_v0;

The target branches straight to the epilogue on the non-NULL path and keeps the maker's result in the register the
helper's result lives in (one `move $s0,$v0`), which no spelling with the work inside the `if` produced: the join's
copy was pulled into the branch delay slot (100), and a `do { } while (0)` fence only reached 10. Returning first and
putting the NULL path's work after it matched (0), with no fence:

    var_s0 = get(); if (var_s0 != NULL) { return var_s0; } ...; var_s0 = make(); ...; return var_s0;

Two families, both pure rewrites of the source text (nothing is compiled here; the exact judge decides every child,
and the compiler's reason is a hypothesis from that one match, not read from its source):

guard_tail_return_hoist
    The function's last two statements are an `if` block without an `else` and `return V;` (V a name or a number).
    The `if` becomes `if (!C) { return V; }` followed by the block's statements and the same `return V;`. `C` is
    negated like early_return_guard_block's (one top-level comparison inverted, a leading `!` dropped, else `!( )`).
    Refused when the block declares a local or holds a label (the statements would change scope), or is empty. It is
    the reverse of early_return_guard_block, which turns an early return into the block.

guard_join_local_unify
    m2c names the call's result `v` and the value made inside the block `s`, and joins them with `v = s;` as the
    block's last statement before `return v;`. When `s` is a local of the same type used only inside that block (first
    use a plain assignment) and `v` is not read inside the block, `s` is renamed to `v` and the copy and `s`'s
    declaration are dropped: one variable carries the pointer from the call to the return.

guard_join_unify_hoist
    Both edits in one child: the unified function then hoisted. Each half alone moves the score a little or not at
    all in a register-allocation-sensitive function (105 -> 100 for the unify alone), so the pair is offered as one.
"""
import re

from .c_scan import close, header_before
from .early_return_guard_block import _negate
from .integer_repair_support import IDENT, edit, view

HOIST = 'guard_tail_return_hoist'
UNIFY = 'guard_join_local_unify'
BOTH = 'guard_join_unify_hoist'
FAMILIES = (HOIST, UNIFY, BOTH)

_VALUE = r'(?:[A-Za-z_]\w*|-?\s*\d+|0[xX][0-9A-Fa-f]+)'
_FINAL = re.compile(rf'\breturn\s+({_VALUE})\s*;(?=\s*$)')
_DECLARATION = re.compile(rf'(?:^|[;{{}}])\s*(?!return\b|if\b|else\b)(?:{IDENT}\s+)+(?:[&*]\s*)*{IDENT}\s*(?:[=;,\[])')
_LABEL = re.compile(rf'(?:^|[;{{}}])\s*{IDENT}\s*:(?!:)')


class _Tail:
    """The function's closing `if (C) { BODY } return V;`, as offsets into the source."""

    def __init__(self, part):
        clean, low, high = part.clean, part.opening + 1, close(part.clean, part.opening)
        self.ok = False
        if high < 0:
            return
        final = _FINAL.search(clean, low, high)
        if not final or clean[final.end():high].strip():
            return
        before = clean[low:final.start()].rstrip()
        if not before.endswith('}'):
            return
        self.block_end = low + len(before) - 1
        depth, i = 0, self.block_end
        while i >= low:
            if clean[i] == '}':
                depth += 1
            elif clean[i] == '{':
                depth -= 1
                if depth == 0:
                    break
            i -= 1
        if i < low or close(clean, i) != self.block_end:
            return
        self.block_start = i
        header = header_before(clean, i)
        match = re.fullmatch(r'if\s*\((.*)\)', header, re.S)
        if not match:
            return
        self.start = clean.rfind(header, 0, i)
        paren = clean.rfind(')', 0, i)
        self.condition_span = (self.start + header.index('(') + 1, paren)
        self.value = re.sub(r'\s+', '', final[1])
        self.return_end = final.end()
        self.body_clean = clean[i + 1:self.block_end]
        self.low = low
        self.ok = bool(self.body_clean.strip())


def _plain(tail):
    body = tail.body_clean
    return not _DECLARATION.search(body) and not _LABEL.search(body)


def _hoist(source, name):
    part = view(source, name)
    tail = _Tail(part) if part else None
    if not tail or not tail.ok or not _plain(tail):
        return None
    c0, c1 = tail.condition_span
    line = source.rfind('\n', 0, tail.start) + 1
    indent = re.match(r'[ \t]*', source[line:tail.start])[0]
    body = source[tail.block_start + 1:tail.block_end].strip('\n').rstrip()
    body = '\n'.join(row[4:] if row.startswith(indent + '    ') else row for row in body.split('\n'))
    text = (f'if ({_negate(source[c0:c1])}) {{\n{indent}    return {tail.value};\n{indent}}}\n'
            f'{body}\n{indent}return {tail.value};')
    return edit(source, [(tail.start, tail.return_end, text)])


def _words(clean, name, low, high):
    return [hit for hit in re.finditer(rf'\b{re.escape(name)}\b', clean[low:high])
            if not re.search(r'(?:\.|->)\s*$', clean[low:high][:hit.start()])]


def _unify(source, name):
    part = view(source, name)
    tail = _Tail(part) if part else None
    if not tail or not tail.ok or not _plain(tail):
        return None
    clean = part.clean
    copy = re.search(rf'(?:^|[;{{}}])\s*({IDENT})\s*=\s*({IDENT})\s*;\s*$', tail.body_clean)
    if not copy or copy[1] != tail.value or copy[1] == copy[2]:
        return None
    kept, moved = copy[1], copy[2]
    low, stop = part.opening + 1, tail.start
    kinds = {}
    for var in (kept, moved):
        found = [hit for hit in re.finditer(
            rf'(?m)^[ \t]*(?P<type>{IDENT}(?:[ \t]+{IDENT})*[ \t]*\**)[ \t]*\b{re.escape(var)}[ \t]*;[ \t]*\n', clean[low:stop])]
        if len(found) != 1 or re.search(r'[{}]', clean[low:low + found[0].start()]):
            return None
        kinds[var] = found[0]
    if re.sub(r'\s+', '', kinds[kept]['type']) != re.sub(r'\s+', '', kinds[moved]['type']):
        return None
    whole = clean[low:close(clean, part.opening)]
    if re.search(rf'&\s*(?:{re.escape(kept)}|{re.escape(moved)})\b', whole):
        return None
    inside = (tail.block_start + 1, tail.block_end)
    for hit in re.finditer(rf'\b{re.escape(moved)}\b', clean[low:close(clean, part.opening)]):
        at = low + hit.start()
        declared = kinds[moved].start() + low <= at < kinds[moved].end() + low
        if not declared and not inside[0] <= at < inside[1]:
            return None
    body = clean[inside[0]:inside[1]]
    first = re.search(rf'\b{re.escape(moved)}\b', body)
    if not first or not re.match(r'\s*=(?!=)', body[first.end():]):
        return None
    uses = [hit for hit in re.finditer(rf'\b{re.escape(kept)}\b', body)]
    if len(uses) != 1 or uses[0].start() != copy.start(1):
        return None
    # `kept` appears in the block only as the copy's target; `moved` is renamed to `kept` everywhere in the block.
    cut = inside[0] + copy.start(1)
    while cut > inside[0] and clean[cut - 1] in ' \t\n':
        cut -= 1
    bound = cut
    end = inside[0] + copy.end()
    renames = [(inside[0] + hit.start(), inside[0] + hit.end(), kept)
               for hit in re.finditer(rf'\b{re.escape(moved)}\b', body) if inside[0] + hit.end() <= bound]
    declaration = kinds[moved]
    edits = renames + [(cut, end, ''), (low + declaration.start(), low + declaration.end(), '')]
    return edit(source, edits)


def variants(source, name, header=''):
    if len(source) > 128000:
        return []
    out = []
    unified = _unify(source, name)
    if unified:
        out.append((UNIFY, unified))
    hoisted = _hoist(source, name)
    if hoisted:
        out.append((HOIST, hoisted))
    if unified and (both := _hoist(unified, name)):
        out.append((BOTH, both))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
