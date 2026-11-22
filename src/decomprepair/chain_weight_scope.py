"""A short value chain wrapped in one-shot scopes so it outranks a neighbouring chain in local allocation, with the
chain's variable split from a later reuse of its name.

GCC 2.x's local allocator (local-alloc.c) gives the registers of a basic block to its quantities in order of
`floor_log2(refs) * refs * size / (death - birth)` and each takes the lowest-numbered free register, so of two chains
that overlap in one straight-line run the one with the higher ratio gets `$v0` and the other `$v1`. flow.c counts a
reference once per loop it sits in (`reg_n_refs += loop_depth`), and a `do { ... } while (0);` is a loop as far as flow.c
is concerned, so a one-shot scope around a statement is one reference more for every pseudo it names at no instruction
cost (`loop_weight_scope`, `call_one_shot_scope` and `argument_weight_scope` do that for counters, one call and a
parameter). Two things make a *chain* (a flag loaded, compared, negated and used as a mask) hard for a one-edit search:

- the scope is also a scheduling barrier (sched.c hangs the loop note on the next insn, which then depends on every
  insn before it), so a scope that holds only the compare moved the compare after the table lookup (80) and one that
  held only the loads moved nothing (35): the loads and the compare go in one scope, the use of the flag in another;
- the chain's variable is often reused later for an unrelated value (`flag = x < n; ...; flag = base + off;`), which
  makes it a multi-set pseudo that local allocation does not take at all (`reg_n_deaths != 1`); the global allocator
  then hands it `$v1` after the other chain took `$v0`. Splitting the later phase into its own local alone was worse
  (35 -> 45).

A 167-instruction KMC GCC 2.7.2 mesh-frame decoder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2 -fno-strength-reduce`)
had one row group left: the frame's validity flag (a `sltu`, `negu`, `and` chain) in `$v1` and the shape-table index in
`$v0`, where the target has them the other way round. The split alone scored 45, the two scopes alone 35, and the
split with both scopes 10 and, with the row loop in its natural form, 0.

`variants` offers, for each local whose assignment `v = expr;` sits in a run of simple statements with at least one
statement between it and a later statement that reads `v` (the mask), the assignment with its neighbour in one scope
and the reader in another, with and without the later reuse of the name split off (`phase_lifetime_repairs`' rewrite).
The explanation (quantity priorities read from the 2.7.2 source, not instrumented in the compiler) is a hypothesis; the
judge decides."""
import re

from . import phase_lifetime_repairs
from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'chain_weight_scope'
FAMILIES = (FAMILY,)
MARK = '/*__repair_chain_scope*/'
PAIR_LIMIT = 3
LIMIT = 24
_CONTROL = re.compile(r'(?:if|for|while|switch|do|else|return|goto|break|continue|case|default)\b')
_LABEL = re.compile(rf'{IDENT}\s*:(?!:)')
_CALL = re.compile(rf'(?<![\w.>])(?!sizeof\b){IDENT}\s*\(')
_ASSIGN = re.compile(rf'(?P<v>{IDENT})\s*=(?!=)\s*(?P<rhs>[^;]*);')


def _end_of_statement(clean, pos, limit):
    """The index after the statement starting at `pos` (a block, a control statement with its `else`s, or one `;`)."""
    while pos < limit and clean[pos].isspace():
        pos += 1
    if pos >= limit:
        return None
    if clean[pos] == '{':
        return close(clean, pos, '{', '}')
    word = _CONTROL.match(clean, pos)
    if word:
        text = word.group(0)
        if text in ('if', 'for', 'while', 'switch'):
            paren = clean.find('(', pos)
            end = close(clean, paren, '(', ')') if paren >= 0 else None
            if end is None:
                return None
            end = _end_of_statement(clean, end, limit)
            while end is not None:
                more = re.match(r'\s*else\b', clean[end:limit])
                if not more:
                    break
                end = _end_of_statement(clean, end + more.end(), limit)
            return end
        if text == 'do':
            end = _end_of_statement(clean, pos + 2, limit)
            tail = re.match(r'\s*while\s*\(', clean[end:limit]) if end else None
            if not tail:
                return None
            paren = end + tail.end() - 1
            end = close(clean, paren, '(', ')')
            semi = re.match(r'\s*;', clean[end:limit]) if end else None
            return end + semi.end() if semi else None
    depth = 0
    for i in range(pos, limit):
        char = clean[i]
        depth += (char in '([') - (char in ')]')
        if char == ';' and depth == 0:
            return i + 1
        if char in '{}':
            return None
    return None


def statements_in(clean, start, limit):
    """The statements of the block between `start` and `limit` (at its own level): (start, end, simple) with `simple`
    for one `v = expr;`-like statement (no call, no `++`, no control flow, no label)."""
    found, pos = [], start
    while True:
        while pos < limit and clean[pos].isspace():
            pos += 1
        if pos >= limit:
            return found
        end = _end_of_statement(clean, pos, limit)
        if end is None:
            return found
        text = clean[pos:end]
        simple = (text.endswith(';') and '{' not in text and not _CONTROL.match(text) and not _LABEL.match(text)
                  and not _CALL.search(text) and '++' not in text and '--' not in text)
        found.append((pos, end, simple))
        pos = end


def _statements(part):
    return statements_in(part.clean, part.opening + 1, part.end - 1)


def _runs(statements):
    run = []
    for index, (_, _, simple) in enumerate(statements):
        if simple:
            run.append(index)
        else:
            if len(run) >= 3:
                yield run
            run = []
    if len(run) >= 3:
        yield run


def _wraps(source, part, scalars):
    """[[(start, end, replacement) ... two scopes] ...] for each chain: the definition with a neighbour, and the reader."""
    statements = _statements(part)
    out = []
    for run in _runs(statements):
        for position, index in enumerate(run):
            start, end, _ = statements[index]
            hit = _ASSIGN.fullmatch(part.clean[start:end])
            if not hit or hit['v'] not in scalars or re.search(rf'(?<![\w.>]){hit["v"]}\b', hit['rhs']):
                continue
            readers = [r for r in run[position + 2:]
                       if re.search(rf'(?<![\w.>]){hit["v"]}\b', part.clean[statements[r][0]:statements[r][1]])]
            if not readers:
                continue
            reader = readers[0]
            definitions = [(index, index + 1)] if index + 1 < reader and index + 1 in run else []
            definitions += [(index - 1, index)] if position > 0 and run[position - 1] == index - 1 else []
            users = [(reader, reader)] + ([(reader, reader + 1)] if reader + 1 in run else [])
            for first in definitions:
                for second in users:
                    scopes = []
                    for low, high in (first, second):
                        low_start, high_end = statements[low][0], statements[high][1]
                        scopes.append((low_start, high_end,
                                       MARK + 'do { ' + source[low_start:high_end].strip() + ' } while (0);'))
                    out.append((hit['v'], scopes))
    return out


def _scoped(source, name):
    part = view(source, name)
    if not part or MARK in source or re.search(r'\b(?:asm|__asm__|setjmp|longjmp|volatile)\b', part.body):
        return []
    scalars = {decl['name'] for decl in locals_for(part)}
    result, seen = [], set()
    for variable, scopes in _wraps(source, part, scalars)[:PAIR_LIMIT * 4]:
        text = edit(source, scopes)
        if text not in seen:
            seen.add(text)
            result.append((variable, text))
    return result


def variants(source, name, header=''):
    out = [(FAMILY, text) for _, text in _scoped(source, name)]
    for split in phase_lifetime_repairs.splits(source, name, header)[:PAIR_LIMIT]:
        out += [(FAMILY, text) for _, text in _scoped(split, name)]
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry (registry.py)
