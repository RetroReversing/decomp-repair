"""The byte reads of a word that several arms assemble the same way, held in locals the arms share.

Two `gSPModifyVertex` arms of a display-list interpreter build the same word from a command's bytes,
`c = (cmd[2] << 24) | (cmd[3] << 16) | (cmd[4] << 8) | cmd[5];` in one and the same at `cmd[-4]..cmd[-1]` in the other.
Each read is an anonymous temporary that lives in one basic block, so local-alloc gives the four of them registers
before global.c runs, starting from `$v0`; the arms' shared values (`c`, the packet pointer) then take what is left
(`$a3` for the pointer where the target has `$a0`, the bytes one register round: `$v0, $v1, $a0, $a1` for the target's
`$v1, $v0, $a1, $a2`). Written through variables both arms assign (`c0 = cmd[2]; c1 = cmd[3]; ...`), the bytes are
global pseudos too, ranked with the pointer by references over live length, and come out in the target's registers.
With each arm's packet pointer back in a block of its own (`{ Gfx *dl = gfx++; ... }`, a block-local quantity again),
the pointer gets `$a0` as well. An SN GCC 2.8.1 model loader (sn-n64-281 `-G0 -mips3 -O2 ... -mfp32`, 618
instructions): 315 -> 60 with the shared byte locals, 0 with the block pointers as well (a shared function-level
pointer kept 60; block pointers without the byte locals were 825). How the allocators order these pseudos is read
from `-dl -dg` dumps of this one function: a hypothesis about the compiler, not checked in its source.

`variants` finds statements `x = E;` where `E` joins (`|`, `+`, shifts, integer literals) at least two element reads
`a[K]` with constant indexes, and where the same `x` is assigned the same shape at least twice. It offers every read
as a new `s32` local all those statements assign (`arm_operand_share`), the reads but the last, and each of those with
the packet pointer of the statements' blocks declared in the block (`arm_operand_share_block_pointer`): when a
function-level pointer `P` is set by the first statement of the block (`{ P = E; ...`) and every reference to `P` in the
function sits after such an assignment in a block that opens with it, the block's `P = E;` becomes `T *P = E;` (the
same program: no value of `P` flows out of a block).
"""
import re

from . import c_scan
from .integer_repair_support import IDENT, _address_taken, edit, view

FAMILY = 'arm_operand_share'
POINTER_FAMILY = 'arm_operand_share_block_pointer'
ORDER_FAMILY = 'arm_operand_share_arm_order'
FAMILIES = (FAMILY, POINTER_FAMILY, ORDER_FAMILY)
LIMIT = 8

_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
READ = re.compile(rf'\b{IDENT}\s*\[\s*-?\s*{_NUMBER}\s*\]')
STATEMENT = re.compile(rf'\b(?P<dst>{IDENT})\s*=\s*(?P<expr>[^;{{}}=!<>]*(?:(?:<<|>>)[^;{{}}=!<>]*)*);')


def _occurrences(part):
    """Every statement `dst = E;` whose E joins two or more constant-index element reads: (match, reads, shape)."""
    found = []
    clean = part.clean
    for hit in STATEMENT.finditer(clean, part.opening + 1, part.end - 1):
        before = clean[part.opening + 1:hit.start()].rstrip()
        if before and before[-1] not in ';{}:':
            continue
        reads = list(READ.finditer(clean, hit.start('expr'), hit.end('expr')))
        if len(reads) < 2:
            continue
        shape = re.sub(r'\s', '', re.sub(_NUMBER, '#', READ.sub('@', hit['expr'])))
        if not re.fullmatch(r'[()@#|+<>]*', shape) or re.search(r'(?<!<)<(?!<)|(?<!>)>(?!>)', shape):
            continue
        found.append((hit, reads, shape))
    return found


def _names(text, dst, count):
    """Fresh names for the operands: `c0..c3`, else `c_op0..`."""
    for pattern in ('{}{}', '{}_op{}', '{}_byte{}'):
        names = [pattern.format(dst, i) for i in range(count)]
        if not any(re.search(rf'\b{name}\b', text) for name in names):
            return names
    return None


def _opening(clean, position, floor):
    """The `{` of the innermost block around `position` (after `floor`, the function's own brace), or -1."""
    return c_scan.enclosing_block(clean, position, floor + 1)


def _set_before(clean, set_end, ref, pointer):
    """Whether the block's assignment (ending at `set_end`) is this reference or comes before it."""
    return set_end <= ref.start() or clean[ref.start():set_end].replace(' ', '').startswith(pointer + '=')


def _block_pointer(part, statement_start):
    """The edit that declares the enclosing block's first-statement pointer in that block, or None."""
    clean = part.clean
    at = _opening(clean, statement_start, part.opening)
    first = re.compile(rf'\{{\s*(?P<p>{IDENT})\s*=\s*[^;{{}}]+;').match(clean, at) if at > part.opening else None
    if not first:
        return None
    pointer = first['p']
    body = clean[part.opening + 1:part.end]
    decl = re.search(rf'(?m)^[ \t]*(?P<type>(?:(?:const|volatile|struct|union|unsigned|signed)\s+)*{IDENT})'
                     rf'\s*(?P<stars>\*[\s*]*){pointer}\s*;', body)
    if not decl or _address_taken(part.body, pointer) or len(re.findall(rf'[\s*]{pointer}\s*[;=,\[)]', body)) < 1:
        return None
    declared = (part.opening + 1 + decl.start(), part.opening + 1 + decl.end())
    sets = {}  # block opening -> the first block-level assignment of the pointer in it
    for hit in re.finditer(rf'(?<=[;{{}}])\s*\b{pointer}\s*=(?!=)', clean[:part.end]):
        if hit.start() > part.opening:
            sets.setdefault(_opening(clean, hit.start(), part.opening), hit.end())
    for ref in re.finditer(rf'\b{pointer}\b', clean[:part.end]):
        if ref.start() <= part.opening or declared[0] <= ref.start() < declared[1]:
            continue
        if clean[max(0, ref.start() - 2):ref.start()] == '->' or clean[ref.start() - 1] == '.':
            continue
        block = _opening(clean, ref.start(), part.opening)
        while block > part.opening and not (block in sets and _set_before(clean, sets[block], ref, pointer)):
            block = _opening(clean, block, part.opening)
        if block <= part.opening:
            return None
    stars = re.sub(r'\s', '', decl['stars'])
    return (first.start('p'), first.start('p'), f'{decl["type"]} {stars}')

_SIMPLE = re.compile(rf'(?<=[;{{}}])(?P<lead>[ \t]*\n?[ \t]*)(?P<dst>{IDENT})\s*=(?!=)(?P<rhs>[^;{{}}]*);')


def _neighbours(part, hit):
    """The plain block-level `y = E;` statements (no calls, no `++`) of the block holding `hit`: {y: match}."""
    clean = part.clean
    block = _opening(clean, hit.start(), part.opening)
    if block <= part.opening:
        return {}
    found = {}
    for other in _SIMPLE.finditer(clean, block, c_scan.close(clean, block) if c_scan.close(clean, block) > 0 else hit.end()):
        if (other['dst'] == hit['dst'] or _opening(clean, other.start('dst'), part.opening) != block
                or re.search(rf'{IDENT}\s*\(|\+\+|--', other['rhs'])):
            continue
        found.setdefault(other['dst'], other)
    return found


def _moves(part, sites):
    """Edits that put each later site's neighbour statements on the side of its word the first site has them, or []."""
    clean = part.clean
    first = _neighbours(part, sites[0][0])
    moves = []
    for hit, _reads in sites[1:]:
        mine = _neighbours(part, hit)
        for var, there in first.items():
            here = mine.get(var)
            if not here or (there.start() < sites[0][0].start()) == (here.start() < hit.start()):
                continue
            lo, hi = sorted((here.end(), hit.start())) if here.start() < hit.start() else (hit.end(), here.start())
            between = clean[lo:hi]
            assigned = set(re.findall(rf'\b({IDENT})\s*=(?!=)', between)) | {hit['dst']}
            if re.search(rf'\b{var}\b', between + hit['expr']) or assigned & set(re.findall(IDENT, here['rhs'])):
                return []
            line = clean.rfind('\n', 0, here.start('dst')) + 1
            text = part.source[here.start('dst'):here.end()] + '\n'
            moves.append((line, here.end() + len(re.match(r'[ \t]*\n?', clean[here.end():]).group(0)), ''))
            if here.start() < hit.start():
                moves.append((hit.end(), hit.end(), '\n' + clean[line:here.start('dst')] + text.rstrip()))
            else:
                moves.append((hit.start(), hit.start(), 'BEFORE:' + text + clean[line:here.start('dst')]))
    return moves


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    jumps = bool(re.search(r'\bgoto\b', part.body))
    groups = {}
    for hit, reads, shape in _occurrences(part):
        groups.setdefault((hit['dst'], shape, len(reads)), []).append((hit, reads))
    integer = 's32' if re.search(r'\bs32\b', (header or '') + source) else 'int'
    top = part.opening + 1
    indent = re.match(r'\n?([ \t]*)', part.clean[top:part.end]).group(1) or '    '
    results = []
    for (dst, _shape, count), sites in groups.items():
        if len(sites) < 2:
            continue
        names = _names((header or '') + source, dst, count)
        if not names:
            continue
        pointers = [None if jumps else _block_pointer(part, hit.start()) for hit, _ in sites]
        for used in (count, count - 1):
            if used < 2:
                continue
            edits = [(top, top, f'\n{indent}{integer} {", ".join(names[:used])};')]
            moves = _moves(part, sites)
            before = {start: text[len('BEFORE:'):] for start, end, text in moves if text.startswith('BEFORE:')}
            moves = [move for move in moves if not move[2].startswith('BEFORE:')]
            plain, ordered = list(edits), list(edits)
            for hit, reads in sites:
                line = part.clean.rfind('\n', 0, hit.start()) + 1
                here = re.match(r'[ \t]*', part.clean[line:]).group(0)
                sets = ''.join(f'{names[i]} = {source[read.start():read.end()]};\n{here}'
                               for i, read in enumerate(reads[:used]))
                plain.append((hit.start(), hit.start(), sets))
                ordered.append((hit.start(), hit.start(), before.get(hit.start(), '') + sets))
                renames = [(read.start(), read.end(), names[i]) for i, read in enumerate(reads[:used])]
                plain += renames
                ordered += renames
            ordered += moves
            choices = [(FAMILY, plain, []), (POINTER_FAMILY, plain, pointers)]
            if moves:
                choices += [(ORDER_FAMILY, ordered, pointers), (ORDER_FAMILY, ordered, [])]
            for family, base, extra in choices:
                if None in extra or len(set(extra)) != len(extra):
                    continue
                text = edit(source, tuple(base + list(extra)))
                if text != source and (family, text) not in results:
                    results.append((family, text))
                if len(results) >= LIMIT:
                    return results
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 700}  # the registry: no caller wiring (registry.py)
