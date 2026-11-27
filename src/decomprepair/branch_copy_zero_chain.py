"""A copy kept apart from its source by a zero the guarded block stores through it.

`level = old - 1; value = level; ... if (hit) { hit->r = value; hit->g = 0; } if (level >= K)` compiled by GCC 2.8.1 (SN
N64) comes out as one register: cse turns the adjacent pair round (`value = old - 1; level = value`, the swap at the end
of cse_insn when the destination outlives the source), then follows the path around the `if` and reads `value` at the
later test, so the copy disappears. The target kept both: `addiu a0,v1,-1; move v1,a0; ... sb v1 ... slti v0,a0,K`.

Two things undo it, neither of which costs an instruction:

* the zero the block stores goes through the copied variable (`hit->g = value = 0;`): cse can no longer carry
  `value == level` past the `if`, and the assignment itself is dead;
* the source of the copy is not the instruction just before it (`level = old - 1;` above an unrelated statement), so the
  swap does not fire.

385 -> 0 with the rest of that function's edits; without the second the first alone leaves a copy the wrong way round
(210), without the first the second alone changes nothing (110).

Offered for `copy = source;` of two plain locals, where `source` was assigned before it, a later `if` block in the same
place reads `copy` and then stores a literal 0 through a member or element, `source` is read after that block and `copy`
is not read again before it is assigned (so the extra zero is never seen). Never inside a loop. A candidate: the judge
decides.
"""
import re

from .c_scan import enclosing_block, header_before
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'branch_copy_zero_chain'
FAMILIES = (FAMILY,)
LIMIT = 8
_COPY = re.compile(rf'(?m)^[ \t]*(?P<copy>{IDENT})[ \t]*=[ \t]*(?P<source>{IDENT})[ \t]*;')
_IF = re.compile(r'\bif\s*\(')
_ZERO = re.compile(rf'(?m)^[ \t]*(?:\(?\*)?{IDENT}(?:\s*(?:->|\.)\s*{IDENT}|\s*\[[^][;]*\])+[ \t]*=[ \t]*(?P<zero>0)[ \t]*;')
_NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_PLAIN = re.compile(rf'(?:{IDENT}|{_NUMBER}|[\s+\-&|^~]|<<|>>)+')


def _local(clean, part, start, name):
    return re.search(rf'(?m)^[ \t]*(?!return\b)(?:(?:unsigned|signed)[ \t]+)?{IDENT}[ \t*]+(?:{IDENT}[ \t]*,[ \t*]*)*{name}'
                     r'[ \t]*(?:[;,])', clean[part.opening:start])


def _in_loop(clean, opening, at):
    brace = enclosing_block(clean, at, opening + 1)
    while brace >= 0:
        if re.search(r'\b(?:for|while|do)\b', header_before(clean, brace)):
            return True
        brace = enclosing_block(clean, brace, opening + 1)
    return False


def _statements_before(clean, at, opening):
    """Spans of the whole lines before `at` that are single simple statements, nearest first."""
    spans = []
    end = clean.rfind('\n', opening, at) + 1
    while len(spans) < 4:
        start = clean.rfind('\n', opening, end - 1) + 1
        line = clean[start:end].strip()
        if not line.endswith(';') or line.count(';') != 1 or re.search(r'[{}:?]|\b(?:if|for|while|do|goto|return|'
                                                                     r'break|continue|case|default)\b', line):
            break
        spans.append((start, end))
        end = start
    return spans


def _risen(source, clean, part, hit):
    """Sources with `source = expr;` (the line just before the copy) moved above one or two unrelated lines."""
    lines = _statements_before(clean, hit.start('copy'), part.opening)
    if len(lines) < 2:
        return []
    start, end = lines[0]
    assign = re.fullmatch(rf'\s*{hit["source"]}\s*=(?!=)\s*(?P<expr>[^;]*);\s*', clean[start:end])
    if not assign or not _PLAIN.fullmatch(assign['expr']):
        return []
    reads = set(re.findall(rf'\b{IDENT}\b', re.sub(rf'\b{_NUMBER}\b', ' ', assign['expr'])))
    if any(not _local(clean, part, start, name) and not re.search(rf'\b{name}\b', clean[:part.opening])
           for name in reads):
        return []
    results = []
    for above, above_end in lines[1:3]:
        line = clean[above:above_end]
        if re.search(rf'\b{hit["source"]}\b', line) or any(
                re.search(rf'(?:\+\+|--)\s*{name}\b|\b{name}\s*(?:\+\+|--|(?:[+\-*/%&|^]|<<|>>)?=(?!=))|&\s*{name}\b', line)
                for name in reads):
            break
        results.append((above, start, end))
    return results


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in _COPY.finditer(clean, part.opening, part.end):
        copy, origin = hit['copy'], hit['source']
        if copy == origin or not _local(clean, part, hit.start(), copy) or not _local(clean, part, hit.start(), origin):
            continue
        if re.search(rf'&\s*(?:{copy}|{origin})\b|\bvolatile\b[^;]*\b(?:{copy}|{origin})\b', clean[part.opening:part.end]):
            continue
        if not re.search(rf'\b{origin}\s*=(?!=)', clean[part.opening:hit.start()]) or _in_loop(clean, part.opening, hit.start()):
            continue
        block = enclosing_block(clean, hit.start(), part.opening)
        for guard in _IF.finditer(clean, hit.end(), part.end):
            if enclosing_block(clean, guard.start(), part.opening) != block:
                continue
            condition = close(clean, guard.end() - 1, '(', ')')
            brace = clean.find('{', condition) if condition else -1
            if brace < 0 or clean[condition:brace].strip():
                continue
            end = close(clean, brace, '{', '}')
            if not end:
                continue
            between = clean[hit.end():guard.start()]
            if re.search(rf'\b{copy}\s*(?:[+\-*/%&|^]|<<|>>)?=(?!=)|\b{origin}\s*(?:[+\-*/%&|^]|<<|>>)?=(?!=)', between):
                break
            body = clean[brace:end]
            reads = list(re.finditer(rf'\b{copy}\b', body))
            if not reads or re.search(rf'\b(?:{copy}|{origin})\s*=(?!=)|\b(?:goto|for|while|do)\b', body):
                continue
            zero = _ZERO.search(body, reads[-1].end())
            if not zero or not re.search(rf'\b{origin}\b', clean[end:part.end]):
                continue
            later = re.search(rf'\b{copy}\b', clean[end:part.end])
            if later and not re.match(r'\s*=(?!=)', clean[end + later.end():]):
                continue
            if later and clean[:end + later.start()].rstrip()[-1:] not in ';{}':
                continue
            at = brace + zero.start('zero')
            chain = (at, at, f'{copy} = ')
            for above, start, stop in _risen(source, clean, part, hit):
                result.append((FAMILY, edit(source, [(above, above, source[start:stop]), (start, stop, ''), chain])))
            result.append((FAMILY, edit(source, [chain])))
            break
        if len(result) >= LIMIT:
            break
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}
