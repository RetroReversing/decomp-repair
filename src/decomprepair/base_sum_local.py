"""Two sums of one base with different addends (`(x + step)` in a statement, `(x + 64)` in a later block) held in one
local: a new one, or a local or parameter that is dead there, set to each sum just before its use.

On a 398-instruction SN64 GCC 2.8.1 glyph printer (`-G0 -mips3 -O2`) the target keeps `x4 + step` (the first
texture rectangle's edge) and `x4 + 64` (the accent's, computed at the head of the `if (ch >= 0xC0)` block, long
before its one use) in one saved register, `$s0`, the parameter's. Written inside the two GFX words, each sum is a
temporary that dies at its mask; the accent's is then computed at its use and the caller-saved registers it frees
shift the whole block's allocation. One variable assigned at both places is a single pseudo with two sets, live
from the block's head to its use, and global.c gives it a saved register: after the flag/quotient local split
(`reused_temp_split`, 4122 -> 4497) this step gave 4122 (the dead parameter; a new local 4137) and `temporary_hoist`
then 3847, the remaining rows register choices in the accent block. The same function's two texture addresses,
`(u32)(font + idx * 0xD0)` and the accent's `(u32)(font + (D_800B28C4[ch - 0xC0] - 0x20) * 0xD0)`, were one `u8 *`
local set before each GFX word (3847 -> 2672; a local for one of them, or one local each, 3117): a pointer base takes
a local of its own type, and the addend may be any expression without side effects. The allocation reading is a
hypothesis; the judge decides.

base_sum_local
    A parenthesised sum `(B + X)` (B a plain identifier, X an expression without assignments or calls that does not
    name B) in one statement, and `(B + Y)` with Y different from X in a statement of a braced block that comes later, does not
    hold the first statement and sits inside the first one's block. Children: a local L set `L = B + X;` before the
    first statement and `L = B + Y;` either as the first statement of the later block or just before the statement
    that uses it, each sum replaced by L. L is a new local (`s32`, or B's own pointer type when B is a pointer local
    declared at the top), or a local of that type declared at the top of the function that neither statement names
    and that is dead at both places (local_flow), or (an integer base) a plain integer parameter whose references all
    come before the first statement in a function with no loops or gotos before the second.
    At most 16 children.
"""
import re

from . import local_flow
from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'base_sum_local'
FAMILIES = (FAMILY,)
LIMIT = 16
WORD = {'s32', 'int', 'signed int', 'long', 'signed', 'u32', 'unsigned int', 'unsigned'}
DECL = re.compile(rf'(?m)^[ \t]*((?:signed\s+|unsigned\s+|const\s+)?{IDENT})[ \t]*(\**)[ \t]*({IDENT})[ \t]*;')
ARRAY = re.compile(rf'(?:(?:signed|unsigned|struct)\s+)?{IDENT}[\s*]+{IDENT}\s*\[[^\]]*\]\s*;')
SUM = re.compile(rf'\(\s*({IDENT})\s*\+(?!\+|=)')
IMPURE = re.compile(rf'\+\+|--|(?<![=!<>])=(?!=)|\b{IDENT}\s*\(|,')
LOOPS = re.compile(r'\b(?:for|while|do|goto)\b')


def _parameters(clean, opening, name):
    hit = re.search(rf'\b{re.escape(name)}\s*\(([^{{}};]*)\)\s*$', clean[:opening])
    found = []
    for piece in (hit[1].split(',') if hit else ()):
        one = re.fullmatch(rf'\s*((?:signed\s+|unsigned\s+)?{IDENT})\s+({IDENT})\s*', piece)
        if one and ' '.join(one[1].split()) in WORD:
            found.append(one[2])
    return found


def _top_locals(clean, part):
    """({name: type} of the integer and pointer locals declared at the top (`u8 *` for a pointer), the end of the
    last top declaration)."""
    names, last = {}, None
    for start, end in statements(clean, part.opening + 1, part.end - 1):
        text = clean[start:end].strip()
        hit = DECL.fullmatch(text)
        if not hit:
            if ARRAY.fullmatch(text):
                last = end
                continue
            break
        last = end
        kind = ' '.join(hit[1].split())
        if hit[2]:
            names[hit[3]] = f'{kind} {hit[2]}'
        elif kind in WORD:
            names[hit[3]] = 's32'
    return names, last


def _innermost(pairs, at):
    """The (open, close) of the innermost block holding `at`."""
    best = None
    for opening, closing in pairs.items():
        if opening < at < closing and (best is None or opening > best[0]):
            best = (opening, closing)
    return best


def _statement(clean, block, at):
    for start, end in statements(clean, block[0] + 1, block[1]):
        if start <= at < end:
            return start, end
    return None


def _sites(part):
    """[(base, (first statement, first sum span), (later block, second statement, second sum span))]."""
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    found = []
    for hit in SUM.finditer(clean, part.opening, part.end):
        end = close(clean, hit.start())
        if end is None or end <= hit.end():
            continue
        addend = ' '.join(clean[hit.end():end - 1].split())
        if not addend or IMPURE.search(addend) or re.search(rf'\b{re.escape(hit[1])}\b', addend):
            continue
        block = _innermost(pairs, hit.start())
        statement = _statement(clean, block, hit.start()) if block else None
        # a sum in an `if`'s condition or a compound statement's header is not one the statement can be set before
        if statement and '{' not in clean[statement[0]:hit.start()]:
            found.append((hit[1], addend, (hit.start(), end), block, statement))
    sites = []
    for base, addend, span, block, statement in found:
        for base2, addend2, span2, block2, statement2 in found:
            if base2 != base or addend2 == addend or span2[0] <= statement[1]:
                continue
            if block2 == block or block2[0] < statement[1] < block2[1] or not block[0] < block2[0] < block[1]:
                continue
            sites.append((base, (statement, span), (block2, statement2, span2)))
    return sites


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def _sum(source, span):
    base, addend = source[span[0] + 1:span[1] - 1].split('+', 1)
    return f'{base.strip()} + {addend.strip()}'


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    sites = _sites(part)
    if not sites:
        return []
    clean = part.clean
    top, last = _top_locals(clean, part)
    params = _parameters(clean, part.opening, name)
    flow = local_flow.analyze(source, name)
    fresh = 'sum'
    while re.search(rf'\b{fresh}\b', clean):
        fresh += '_'
    decl_at = (clean.find('\n', last) + 1) if last is not None else clean.find('\n', part.opening) + 1
    indent = _indent(source, clean.find('\n', part.opening) + 1) or '    '
    body = clean[part.opening:part.end]
    out = []
    for base, (statement, span), (block2, statement2, span2) in sites:
        kind = top.get(base, 's32')
        named = clean[statement[0]:statement[1]] + clean[statement2[0]:statement2[1]]
        first = next((start for start, _ in statements(clean, block2[0] + 1, block2[1])), statement2[0])
        places = [first] if first == statement2[0] else [first, statement2[0]]
        choices = [(fresh, True)]
        if flow is not None:
            nodes = [flow.at(statement[0]), flow.at(statement2[0]), flow.at(first)]
            for local, its in top.items():
                if its != kind or local == base or re.search(rf'\b{re.escape(local)}\b', named):
                    continue
                if any(node is None or local in node.live for node in nodes) or nodes[0].start != statement[0]:
                    continue
                choices.append((local, False))
        if kind == 's32' and not LOOPS.search(clean[part.opening:statement2[1]]):
            for param in params:
                if param == base or re.search(rf'&\s*{re.escape(param)}\b', body):
                    continue
                if all(part.opening + hit.start() < statement[0]
                       for hit in re.finditer(rf'\b{re.escape(param)}\b', body)):
                    choices.append((param, False))
        for local, new in choices:
            for place in places:
                edits = [(statement[0], statement[0], f'{local} = {_sum(source, span)};\n{_indent(source, statement[0])}'),
                         (span[0], span[1], local),
                         (place, place, f'{local} = {_sum(source, span2)};\n{_indent(source, place)}'),
                         (span2[0], span2[1], local)]
                if new:
                    pointer = kind.endswith('*')
                    edits.append((decl_at, decl_at, f'{indent}{kind}{"" if pointer else " "}{local};\n'))
                result = edit(source, edits)
                if result != source and (FAMILY, result) not in out:
                    out.append((FAMILY, result))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # registry: no wiring
