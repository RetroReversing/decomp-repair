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
The judge decides, and no child is a verdict."""
import re

from .integer_repair_support import IDENT, edit, view
from .run_weight_scope import _CONTROL, _LABEL, _block_statements, _inner

FAMILY = 'independent_statement_swap'
FAMILIES = (FAMILY,)
LIMIT = 80
_NAME = re.compile(IDENT)
_CALL = re.compile(rf'(?<![\w.>])(?!(?:if|while|for|switch|return|sizeof)\b){IDENT}\s*\(')
_NEUTRAL = re.compile(rf'\b(?:inline_fn\d*|__repair_\w+)\b')


def _left(text):
    hit = re.match(r'\s*(.*?)(?<![=!<>])(?:[-+*/%&|^]|<<|>>)?=(?!=)', text, re.S)
    return hit[1].strip() if hit else ''


def _assigned(text):
    """({local names assigned}, whether the statement writes through memory)."""
    left = _left(text)
    if re.fullmatch(IDENT, left):
        return {left}, False
    return set(), bool(left)


def independent(first, second):
    """Whether two simple statements may trade places: a hypothesis about the program, which the judge then tests."""
    first, second = first.strip(), second.strip()
    for text in (first, second):
        if _CALL.search(_NEUTRAL.sub('', text)) or not text.endswith(';') or '=' not in text:
            return False
    written_a, memory_a = _assigned(first)
    written_b, memory_b = _assigned(second)
    if (written_a & set(_NAME.findall(second))) or (written_b & set(_NAME.findall(first))):
        return False
    if memory_a and memory_b and _left(first) == _left(second):
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
    if not part or re.search(r'\b(?:asm|__asm__|volatile|setjmp|longjmp)\b|^\s*#', part.clean[:part.end], re.M):
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
