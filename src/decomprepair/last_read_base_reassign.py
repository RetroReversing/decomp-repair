"""The last of several reads off one base pointer reassigns the base to its sum, the earlier read held in a local.

m2c writes a function that subtracts (or adds, or ors) two record fields found through one table base as one
expression, the base summed with a scaled index inside each read:

    temp2 = (u16 *)((s8 *)(temp + (idxA * 0x510)) + 0x418);
    return (*temp2) - (*(u16 *)((s8 *)(temp + (idxB * 0x510)) + 0x418));

On a KMC GCC 2.7.2 (`-O1 -g`, SN `sn-n64-272-0001`) build the target sums the last lookup into the dying base register
(`addu $a2,$a2,$v0; lhu $v0,0x418($a2)`) where the nested sum is formed in the result register
(`addu $v0,$v0,$a2; lhu $v0,0x418($v0)`): 10 rows differing, 0 once the base is assigned its own last sum and read
through (the match was found by hand in a 3-lookup-per-pair sort comparator):

    s32 first;
    temp2 = (u16 *)((s8 *)(temp + (idxA * 0x510)) + 0x418);
    first = *temp2;
    temp = temp + (idxB * 0x510);
    return first - *(u16 *)((s8 *)temp + 0x418);

The reading (a pseudo that is both set and used by the same add is tied to its source by local-alloc's
`combine_regs`, so the dead base's register takes the sum) is a hypothesis; the judge decides.

last_read_base_reassign
    A `return A OP B;` (OP the lowest-precedence binary operator at the top of the expression, last occurrence; `|`,
    `^`, `&`, then `+ -`, then `*`) whose last operand B holds exactly one `(P + X)` of a local or parameter P (a
    pointer, or the integer a table's address is held in, as m2c writes a loaded base; X without assignments or calls, not naming P) and does not otherwise name P, while the function names `P + ...`
    earlier too (an address local set before, or A), and P is not read after the return (the return ends the
    function, or nothing names P later and there is no loop or goto), and the function returns an integer. Child:
    `first = A;`, `P = P + X;`, `return first OP B'` with `(P + X)` in B replaced by `P`. `first` is a new `s32`
    local (declared after the function's leading declarations). One child per return, at most 8.
"""
import re

from .arm_block_support import statements
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'last_read_base_reassign'
FAMILIES = (FAMILY,)
LIMIT = 8
INTEGERS = {'s32', 'u32', 'int', 'signed int', 'unsigned int', 'unsigned', 'signed', 'long', 'unsigned long',
            's16', 'u16', 's8', 'u8', 'short', 'unsigned short', 'char', 'unsigned char', 's64', 'u64'}
GROUPS = (('|',), ('^',), ('&',), ('+', '-'), ('*',))
DECL = re.compile(rf'(?:(?:signed|unsigned|const|struct)\s+)*{IDENT}[\s*]+{IDENT}(?:\s*\[[^\]]*\])*\s*;')
SUM = re.compile(rf'(?<![\w.>\]])\(\s*({IDENT})\s*\+(?!\+|=)')
IMPURE = re.compile(rf'\+\+|--|(?<![=!<>])=(?!=)|\b{IDENT}\s*\(|,')
LOOPS = re.compile(r'\b(?:for|while|do|goto)\b')


def _split(text):
    """(left, operator, right) at the last top-level binary operator of the lowest-precedence group present."""
    depth, found = 0, {}
    for at, char in enumerate(text):
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif depth == 0 and char in '|^&+-*' and 0 < at < len(text) - 1 and text[at - 1] == ' ' and text[at + 1] == ' ':
            found.setdefault(char, []).append(at)
    for group in GROUPS:
        marks = [at for char in group for at in found.get(char, ())]
        if marks:
            at = max(marks)
            return text[:at].strip(), text[at], text[at + 1:].strip()
    return None


def _return_end(clean, start):
    depth = 0
    for at in range(start, len(clean)):
        if clean[at] in '([{':
            depth += 1
        elif clean[at] in ')]}':
            depth -= 1
        elif clean[at] == ';' and depth == 0:
            return at
    return None


def _returns_integer(clean, opening, name):
    head = clean[:opening]
    hit = re.search(rf'((?:[\w]+\s+)*[\w]+)[\s*]+{re.escape(name)}\s*\(', head)
    if not hit or '*' in head[hit.start():hit.end()]:
        return False
    words = [w for w in hit[1].split() if w not in ('static', 'extern', 'inline')]
    return ' '.join(words) in INTEGERS


def _leading(clean, part):
    """(the end of the leading declarations, their text)."""
    last = None
    for start, end in statements(clean, part.opening + 1, part.end - 1):
        if not DECL.fullmatch(clean[start:end].strip()):
            break
        last = end
    return last


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:])[0]


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip() or not _returns_integer(part.clean, part.opening, name):
        return []
    clean = part.clean
    if '#' in clean[part.opening:part.end]:
        return []
    leading = _leading(clean, part)
    decl_at = (clean.find('\n', leading) + 1) if leading is not None else clean.find('\n', part.opening) + 1
    declared = clean[:decl_at]
    tops = list(statements(clean, part.opening + 1, part.end - 1))
    fresh = 'first'
    while re.search(rf'\b{fresh}\b', clean):
        fresh += '_'
    loops = bool(LOOPS.search(clean[part.opening:part.end]))
    out = []
    for hit in re.finditer(r'\breturn\b', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        end = _return_end(clean, start)
        before = clean[:start].rstrip()
        if end is None or not before or before[-1] not in ';{}':
            continue
        parts = _split(clean[start + len('return'):end])
        if not parts:
            continue
        left, op, right = parts
        sums = list(SUM.finditer(right))
        if len(sums) != 1:
            continue
        base = sums[0][1]
        stop = close(right, sums[0].start())
        if stop is None:
            continue
        addend = ' '.join(right[sums[0].end():stop - 1].split())
        rest = right[:sums[0].start()] + right[stop:]
        if (not addend or IMPURE.search(addend) or re.search(rf'\b{re.escape(base)}\b', addend + rest)
                or '*' not in left or IMPURE.search(left)):
            continue
        if not re.search(rf'\w[\s*]+{re.escape(base)}\s*[;,)\[]', declared):
            continue
        if not re.search(rf'(?<![\w.>\]])\(?\s*{re.escape(base)}\s*\+(?!\+|=)', clean[part.opening:start] + left):
            continue
        later = clean[end:part.end]
        if start != tops[-1][0]:
            if loops or re.search(rf'\b{re.escape(base)}\b', later):
                continue
        indent = _indent(source, start)
        replaced = right[:sums[0].start()] + base + right[stop:]
        lines = (f'{fresh} = {left};\n{indent}{base} = {base} + {addend};\n{indent}'
                 f'return {fresh} {op} {replaced};')
        result = edit(source, [(decl_at, decl_at, f'{_indent(source, clean.find(chr(10), part.opening) + 1) or "    "}'
                                f's32 {fresh};\n'), (start, end + 1, lines)])
        if result != source and (FAMILY, result) not in out:
            out.append((FAMILY, result))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # registry: no wiring
