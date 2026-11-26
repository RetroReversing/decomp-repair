"""A power-of-two signed division's dividend staged in a local of its own (`t = E; v = K - t / 2;`), a new one or a
local that is dead there.

GCC expands `E / 2` for a signed int as `t = E; u = t + (t >> 31 unsigned); u >> 1`. With E written inside the
expression, its pseudo is a temporary that dies at the add, so local-alloc ties the add's result to it (`addu $v1, $v1,
$v0`); written into a local first, the dividend is a user variable (`REG_USERVAR_P`), and when that local is one the
function also uses elsewhere (a global pseudo) the block's quantities are numbered and tied in another order: on a
320-instruction SN64 GCC 2.8.1 options menu (`-G0 -mips3 -O2 -mfp64`) the colour `0xFF - ((cos * 127 >> 15) + 0x80) / 2`
took the target's `addu $v0, $v1, $v0; sra $v0, $v0, 1` once the dividend went into the clamp's local, dead at that
point (100 -> 85); a new local or another dead local left it at 100. The local-alloc reading is a hypothesis; the
judge decides.

dividend_local_stage
    A statement `L = R;` (L a plain lvalue, the statement free of side effects outside the dividend) whose R holds
    `(E) / N` with N a power of two, becomes `t = E; L = R';` with `(E)` replaced by `t`: one child with a new `s32`
    local, one for each integer local declared at the top of the function that the statement does not name and that is
    dead there and after it (local_flow). At most 16 children.
"""
import re

from . import local_flow
from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'dividend_local_stage'
FAMILIES = (FAMILY,)
LIMIT = 16
WORD = {'s32', 'int', 'signed int', 'long', 'signed', 's16', 'short'}
DECL = re.compile(rf'(?m)^[ \t]*((?:signed\s+)?{IDENT})[ \t]+({IDENT})[ \t]*;')
ARRAY = re.compile(rf'(?:(?:signed|unsigned|struct)\s+)?{IDENT}[\s*]+{IDENT}\s*\[[^\]]*\]\s*;')


def _pure(text):
    return not re.search(r'\+\+|--|,|(?<![=!<>])=(?!=)', text) and not re.search(rf'\b{IDENT}\s*\(', text)


def _power_of_two(text):
    text = text.rstrip('uUlL')
    try:
        value = int(text, 0)
    except ValueError:
        return False
    return value >= 2 and value & (value - 1) == 0


def _sites(part):
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    sites = []
    for block_open, block_close in sorted(pairs.items()):
        for start, end in statements(clean, block_open + 1, block_close):
            text = clean[start:end]
            hit = re.fullmatch(rf'\s*(?P<lv>{IDENT}(?:\s*(?:->|\.)\s*{IDENT})*)\s*=(?!=)(?P<rhs>[^;{{}}]*);\s*', text)
            if not hit:
                continue
            rhs_at = start + hit.start('rhs')
            for div in re.finditer(r'\)\s*/\s*((?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*)\b', clean[rhs_at:start + hit.end('rhs')]):
                if not _power_of_two(div[1]):
                    continue
                close_at = rhs_at + div.start()
                depth, open_at = 0, None
                for at in range(close_at, rhs_at - 1, -1):
                    if clean[at] == ')':
                        depth += 1
                    elif clean[at] == '(':
                        depth -= 1
                        if depth == 0:
                            open_at = at
                            break
                if open_at is None or close(clean, open_at) != close_at + 1:
                    continue
                # `f(a) / 2` is a call's result and `(T) (x) / 2` a cast: neither is a parenthesised dividend
                if re.search(r'(?:\w|\))$', clean[rhs_at:open_at].rstrip()):
                    continue
                inner = clean[open_at + 1:close_at].strip()
                outside = clean[rhs_at:open_at] + clean[close_at + 1:end]
                if not inner or not _pure(outside) or not re.search(r'[-+*&|^<>]', inner):
                    continue
                sites.append((start, end, open_at, close_at + 1, inner))
    return sites


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    sites = _sites(part)
    if not sites:
        return []
    clean = part.clean
    top = []
    for start, end in statements(clean, part.opening + 1, part.end - 1):
        text = clean[start:end].strip()
        hit = DECL.fullmatch(text)
        if not hit:
            if ARRAY.fullmatch(text):
                continue
            break
        if ' '.join(hit[1].split()) in WORD:
            top.append(hit[2])
    flow = local_flow.analyze(source, name)
    fresh = 'stg'
    while re.search(rf'\b{fresh}\b', clean):
        fresh += '_'
    last = None
    for start, end in statements(clean, part.opening + 1, part.end - 1):
        if not DECL.fullmatch(clean[start:end].strip()) and not ARRAY.fullmatch(clean[start:end].strip()):
            break
        last = end
    decl_at = (clean.find('\n', last) + 1) if last is not None else clean.find('\n', part.opening) + 1
    indent = re.match(r'[ \t]*', source[clean.find('\n', part.opening) + 1:])[0] or '    '
    out = []
    for start, end, open_at, close_at, inner in sites:
        line = source.rfind('\n', 0, start) + 1
        own = re.match(r'[ \t]*', source[line:start])[0] if not source[line:start].strip() else indent
        statement = clean[start:end]
        choices = [(fresh, True)]
        node = flow.at(start) if flow else None
        if node is not None and node.start == start:
            following = set().union(*(flow.nodes[n].live for n in node.successors)) if node.successors else set()
            for local in top:
                if re.search(rf'\b{re.escape(local)}\b', statement):
                    continue
                if local in node.live or local in following:
                    continue
                choices.append((local, False))
        for local, new in choices:
            edits = [(start, start, f'{local} = {source[open_at + 1:close_at - 1].strip()};\n{own}'),
                     (open_at, close_at, local)]
            if new:
                edits.append((decl_at, decl_at, f'{indent}s32 {local};\n'))
            result = edit(source, edits)
            if result != source and (FAMILY, result) not in out:
                out.append((FAMILY, result))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # registry: no wiring
