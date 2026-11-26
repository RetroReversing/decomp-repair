"""Bit fields pulled out of one word, `a = (v >> 5) & 0x1F; b = (v >> 10) & 0x1F;`, written shifts first, masks after.

A triangle command packs three 5-bit vertex indices in a halfword. Written one field per statement (`x = (v >> 5) &
0x1F;`), each shift's result is a pseudo that dies in its own `and`, and local-alloc ties the two: the field lands in
whatever register the shift had, interleaved with the next shift. Written as the shifts into the fields' own variables
and then the masks in place (`a = v >> 5; b = v >> 10; a &= 0x1F; b &= 0x1F;`), every field variable is set twice,
lives from its shift to its mask, and the block's registers come out in the order of the shifts (`srl $a2, $a1, 5;
move $v0, $a1; sra $a1, $a1, 0xa; andi $a0, $v0, 0x1f; andi $a2, $a2, 0x1f; andi $a1, $a1, 0x1f`). An SN GCC 2.8.1 model
loader (sn-n64-281, 618 instructions), its gSP1Triangle and gSP2Triangles arms: 825 -> 580 with the three blocks
written this way (under `-mfp32`: 775 -> 550 for one block, 530 for all three). The reading of local-alloc is a
hypothesis from the output; the judge decides.

`variants` takes each run of adjacent simple assignments in a block (`x = e;` or `x op= e;`, no calls, no `++`/`--`),
splits every `x = (e >> k) & M;` into `x = e >> k;` and a mask `x &= M;`, and orders the run as its shifts and other
statements first and its masks (also `y = x & M;`) after them, each group in its old order, when no statement it moves
reads or writes what another one it passes writes. Children: each run on its own, each split statement's mask moved to
the end of its run on its own, and every run together.
"""
import re

from . import c_scan
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'field_mask_defer'
FAMILIES = (FAMILY,)
LIMIT = 10
STATEMENT = re.compile(
    rf'(?P<head>[ \t]*)(?P<lhs>{IDENT})\s*(?P<op>[-+*/|&^]|<<|>>)?=(?!=)\s*(?P<rhs>[^;{{}}]+?)\s*;')
SPLIT = re.compile(rf'\(\s*(?P<shift>[^;{{}}]*?>>\s*{NUMBER})\s*\)\s*&\s*(?P<mask>{NUMBER})')
MASK = re.compile(rf'{IDENT}\s*&\s*{NUMBER}')


def _names(text):
    return set(re.findall(rf'(?<![\w.>]){IDENT}(?!\s*\()', text)) - {'u8', 's8', 'u16', 's16', 'u32', 's32', 'int',
                                                                         'unsigned', 'signed', 'char', 'short'}


def _statements(clean, lo, hi):
    """Runs of adjacent simple assignments between lo and hi (a gap that is not one ends a run)."""
    runs, run, at = [], [], lo
    for hit in STATEMENT.finditer(clean, lo, hi):
        rhs = hit['rhs']
        simple = not re.search(rf'\+\+|--|\b{IDENT}\s*\(', rhs)
        if clean[at:hit.start()].strip() or not simple:
            if len(run) > 1:
                runs.append(run)
            run = []
        if simple:
            run.append(hit)
        at = hit.end()
    if len(run) > 1:
        runs.append(run)
    return runs


def _indent(clean, hit):
    line = clean.rfind('\n', 0, hit.start('lhs')) + 1
    head = clean[line:hit.start('lhs')]
    return head if not head.strip() else re.match(r'[ \t]*', head).group()


def _pieces(hit):
    """(kind, text, writes, reads) for a statement: kind 'shift' or 'mask'; a split statement gives both."""
    lhs, op, rhs = hit['lhs'], hit['op'], hit['rhs']
    split = None if op else SPLIT.fullmatch(rhs)
    if split:
        return [('shift', f'{lhs} = {split["shift"].strip()};', {lhs}, _names(split['shift'])),
                ('mask', f'{lhs} &= {split["mask"]};', {lhs}, {lhs})], True
    kind = 'mask' if (op == '&' and re.fullmatch(NUMBER, rhs.strip())) or (not op and MASK.fullmatch(rhs.strip())) \
        else 'shift'
    reads = _names(rhs) | ({lhs} if op else set())
    return [(kind, f'{lhs} {op or ""}= {rhs};', {lhs}, reads)], False


def _order(pieces):
    """Stable partition: non-masks first, masks after; None when a moved piece depends on one it passes."""
    moved = [p for p in pieces if p[0] != 'mask'] + [p for p in pieces if p[0] == 'mask']
    position = {id(p): i for i, p in enumerate(pieces)}
    for i, a in enumerate(moved):
        for b in moved[i + 1:]:
            if position[id(a)] > position[id(b)] and (a[2] & (b[2] | b[3]) or b[2] & a[3]):
                return None
    return moved


def _rewrite(clean, run, chosen):
    """Edits for one run: `chosen` is the set of split statements to split (all pieces reordered when full)."""
    pieces, any_split = [], False
    for hit in run:
        parts, split = _pieces(hit)
        if split and hit.start() not in chosen:
            parts = [('shift', clean[hit.start('lhs'):hit.end()], {hit['lhs']}, _names(hit['rhs']))]
        any_split |= split and hit.start() in chosen
        pieces.extend(parts)
    if not any_split:
        return None
    ordered = _order(pieces)
    if not ordered:
        return None
    head = _indent(clean, run[0])
    text = ('\n' + head).join(p[1] for p in ordered)
    return [(run[0].start('lhs'), run[-1].end(), text)]


def _defer_one(clean, run, hit):
    """One split statement's mask moved to the end of its run, the rest left in place."""
    parts, split = _pieces(hit)
    later = run[run.index(hit) + 1:]
    if not split or not later or any(hit['lhs'] in _names(h['rhs']) or h['lhs'] == hit['lhs'] for h in later):
        return None
    head = _indent(clean, run[0])
    return [(hit.start('lhs'), hit.end(), parts[0][1]), (run[-1].end(), run[-1].end(), f'\n{head}{parts[1][1]}')]


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    runs = []
    for opening in [part.opening] + [m.start() for m in re.finditer(r'{', clean[part.opening + 1:part.end])]:
        opening = opening if opening == part.opening else opening + part.opening + 1
        close = c_scan.close(clean, opening)
        if close < 0:
            continue
        # this block's own statements: skip nested blocks by blanking them
        inner = list(clean[opening + 1:close])
        for nested in re.finditer(r'{', clean[opening + 1:close]):
            start = nested.start() + opening + 1
            end = c_scan.close(clean, start)
            if end > 0:
                inner[start - opening - 1:end - opening] = '#' * (end - start + 1)
        text = clean[:opening + 1] + ''.join(inner) + clean[close:]
        for run in _statements(text, opening + 1, close):
            if any(SPLIT.fullmatch(h['rhs']) and not h['op'] for h in run):
                runs.append(run)
    results = []

    def add(edits):
        if edits:
            out = edit(source, tuple(edits))
            if out != source and (FAMILY, out) not in results:
                results.append((FAMILY, out))

    full = [_rewrite(clean, run, {h.start() for h in run}) for run in runs]
    for edits in full:
        add(edits)
    for run in runs:
        for hit in run:
            add(_defer_one(clean, run, hit))
    if len([e for e in full if e]) > 1:
        add([e for edits in full if edits for e in edits])
    return results[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 700}  # the registry: no caller wiring (registry.py)
