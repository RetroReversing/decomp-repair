"""Two neighbouring statements that cannot depend on each other, written in the other order.

`adjacent_cast_store_swap` swaps two stores of one base. The scheduler (sched.c, one list pass before allocation, one after)
orders independent insns by priority and, among equal ones, by the order the statements came, so two statements the source
has the other way round are two different insn orders and, behind them, two different allocations. On an 874-instruction KMC
N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`) `*arg0 = rec; ((R *) rec)->f = v;` written the other way took 1691 ->
1551 (the exact judge, also the app's `compile_and_diff`), and no family offered it: the two stores have different bases.

`variants` takes each pair of consecutive simple statements of one block (an assignment or a call-free expression; not a
declaration, control flow, label, `case`, `asm` or `volatile`) and swaps the pair when neither statement assigns a name the
other mentions, neither holds a call, and, if both write through memory, their left sides differ and neither reads memory
through the other's left side. One child per pair, at most `LIMIT`, the pairs that sit in the most-referenced blocks first.
The judge decides, and no child is a verdict.

m2c's own drafts were never read: they open with `#ifndef M2C_DEFINES` (a directive anywhere above the function refused
it) and spell every field `M2C_FIELD(base, type *, offset)`, which looked like a call. Directives now refuse only inside
the function, and the field macro is a cell: it trades places unless the other statement touches overlapping bytes of the
same base. A 52-instruction N64 pickup initialiser (SN GCC 2.8.1 `-G0 -mips3 -O2`) wanted `G = 1; T[M2C_FIELD(..)] = 1;`
written the other way round (1060 -> 820 on the m2c draft; 0 with the table retyped by `scaled_byte_table_element`).

A lone `X++;` or `X--;` is read as `X += 1;`: it has no `=`, so `p->frames++; p->x += 40;` was never offered the other
way round. On an SN GCC 2.8.1 N64 object-update routine (263 instructions) that swap alone took 60 -> 0."""
import re

from .integer_repair_support import IDENT, edit, view
from .run_weight_scope import _CONTROL, _LABEL, _block_statements, _inner

FAMILY = 'independent_statement_swap'
FAMILIES = (FAMILY,)
LIMIT = 80
_NAME = re.compile(IDENT)
# `p->count++;` on a line of its own is the assignment `p->count += 1;`
_STEP = re.compile(r'^(?P<x>[^=;+\-]*(?:->[^=;+\-]*)*?)\s*(?P<op>[+-])(?P=op)\s*;$')
_CALL = re.compile(rf'(?<![\w.>])(?!(?:if|while|for|switch|return|sizeof)\b){IDENT}\s*\(')
_NEUTRAL = re.compile(r'\b(?:inline_fn\d*|__repair_\w+|M2C_FIELD)\b')
_FIELD = re.compile(r'\bM2C_FIELD\(\s*([^,]+?)\s*,\s*([^,()]+?)\s*,\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\s*\)')
_WIDTHS = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
           'float': 4, 's64': 8, 'u64': 8, 'f64': 8, 'double': 8}


def _left(text):
    hit = re.match(r'\s*(.*?)(?<![=!<>])(?:[-+*/%&|^]|<<|>>)?=(?!=)', text, re.S)
    return hit[1].strip() if hit else ''


def _assigned(text):
    """({local names assigned}, whether the statement writes through memory)."""
    left = _left(text)
    if re.fullmatch(IDENT, left):
        return {left}, False
    return set(), bool(left)


def _cell(hit):
    """(base, first byte, end) of one `M2C_FIELD`; an unknown type is taken to be 8 bytes wide."""
    spelled = hit[2].strip()
    if spelled.count('*') > 1:
        width = 4
    else:
        width = _WIDTHS.get(spelled.rstrip('* ').split()[-1], 8)
    start = int(hit[3], 0)
    return re.sub(r'\s+', '', hit[1]), start, start + width


def _field_clash(first, second):
    """Whether the field `first` stores to shares bytes with one `second` reads or writes through the same base."""
    hit = _FIELD.fullmatch(_left(first))
    if not hit:
        return False
    base, start, end = _cell(hit)
    return any(other == base and start < stop and begin < end
               for other, begin, stop in map(_cell, _FIELD.finditer(second)))


def independent(first, second):
    """Whether two simple statements may trade places: a hypothesis about the program, which the judge then tests."""
    first, second = (_STEP.sub(r'\g<x> \g<op>= 1;', text.strip()) for text in (first, second))
    for text in (first, second):
        if _CALL.search(_NEUTRAL.sub('', text)) or not text.endswith(';') or '=' not in text:
            return False
    written_a, memory_a = _assigned(first)
    written_b, memory_b = _assigned(second)
    if (written_a & set(_NAME.findall(second))) or (written_b & set(_NAME.findall(first))):
        return False
    if memory_a and memory_b and _left(first) == _left(second):
        return False
    if _field_clash(first, second) or _field_clash(second, first):
        return False
    right_a, right_b = first[len(_left(first)):], second[len(_left(second)):]
    if memory_a and not memory_b and re.search(r'\*|->', right_b):
        return False
    if memory_b and not memory_a and re.search(r'\*|->', right_a):
        return False
    if memory_a and memory_b:
        # a store whose value reads memory beside another store: only when the value names none of the other's bases
        bases_a, bases_b = set(_NAME.findall(_left(first))), set(_NAME.findall(_left(second)))
        if re.search(r'\*|->', right_a) and set(_NAME.findall(right_a)) & bases_b:
            return False
        if re.search(r'\*|->', right_b) and set(_NAME.findall(right_b)) & bases_a:
            return False
    return True


def variants(source, name):
    part = view(source, name)
    if (not part or re.search(r'\b(?:asm|__asm__|volatile|setjmp|longjmp)\b', part.clean[:part.end])
            or re.search(r'^\s*#', part.clean[part.opening:part.end], re.M)):
        return []
    clean = part.clean
    pairs = []
    for start, end in sorted(set(_inner(clean, part.opening + 1, part.end - 1))):
        listed = _block_statements(clean, start, end)
        for (a, b, compound_a), (c, d, compound_b) in zip(listed, listed[1:]):
            if compound_a or compound_b or clean[b:c].strip():
                continue
            text = clean[a:b] + clean[c:d]
            if _CONTROL.search(text) or _LABEL.search(text):
                continue
            if independent(clean[a:b], clean[c:d]):
                pairs.append((a, b, c, d))
    result = []
    for a, b, c, d in sorted(set(pairs))[:LIMIT]:
        result.append((FAMILY, edit(source, [(a, d, source[c:d] + source[b:c] + source[a:b])])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
