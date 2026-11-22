"""A reused pointer local and the stray trailing arguments m2c passes it as: two edits that only pay off together.

m2c names the register a callee's argument slot still holds and passes it on: `func_80022E88(3, temp_a1);` where the
callee reads one argument, and the same name carries the pointer loaded before and after a store. KMC GCC 2.7.2 (`-G0
-mips3 -mgp32 -mfp32 -O2`) is sensitive to both in ways that look unrelated:

  - every `(set (reg a1) ...)` the first scheduler sees counts in `reg_n_sets` of the hard register. The first
    scheduler (sched.c `birthing_insn_p`) launches an insn directly before its consumer only when its destination is a
    live register set exactly once, so a function with two extra `a1` sets in stray arguments leaves the byte-argument
    chain `andi $a1` unlaunched and the whole argument run schedules in another order (the loads of a call's
    arguments before a multiply chain instead of the chain's first shift between them);
  - one pointer local assigned twice (a load before a store through it, the same field again after) is one pseudo with
    the long life of both. Its register choice is steered by the preference of a parameter's copy that lives across
    both; with the second load in a pseudo of its own, the first takes the argument register and the parameter's copy
    moves to `$a3`, as the target has it.

Alone, dropping the stray arguments scored 790 and splitting the pointer scored 60 on a 140-instruction KMC menu
function (60 -> 0 together); a matched twin of the same menu code (its source had neither the stray arguments nor the
reuse) is the evidence that the pair is the original's. The explanation above is read from `sched.c` and `global.c`
(hypothesis for the register effect, which was measured only); the exact judge decides.

The shape: a function whose calls end in a local pointer variable (never a parameter) for callees declared with an
empty parameter list (`s32 f();`), with that variable assigned twice by plain statements of one block. One child
drops the trailing argument from every such call and renames the second assignment's span to a pointer local of its
own; each half is offered alone as well. Nothing is offered where a goto, label, switch or loop could reach a read of
the old value out of order.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'call_carrier_pointer_split'
DROP_FAMILY = 'call_carrier_argument_drop'
SPLIT_FAMILY = 'call_carrier_pointer_reuse_split'
FAMILIES = (FAMILY, DROP_FAMILY, SPLIT_FAMILY)

IDENT = r'[A-Za-z_]\w*'
POINTER_DECL = re.compile(rf'(?m)^([ \t]*)((?:struct\s+|union\s+|unsigned\s+|signed\s+)?{IDENT})([ \t]*\*+[ \t]*)({IDENT})[ \t]*;[ \t]*\n')
CALL = re.compile(rf'(?<![\w.>])(?P<f>{IDENT})\s*\(')
UNORDERED = re.compile(r'\b(?:goto|switch|for|while|do|asm|__asm__|setjmp|longjmp)\b|^\s*#', re.M)


def _params(clean, part):
    signature = clean[:part.opening]
    start = signature.rfind('(')
    return set(re.findall(rf'({IDENT})\s*(?:,|\))', signature[start + 1:] + ')'))


def _arguments(clean, start, end):
    """The top-level argument spans of a call whose `(` is at `start - 1` and `)` at `end`."""
    spans, depth, begin = [], 0, start
    for index in range(start, end):
        char = clean[index]
        depth += (char in '([{') - (char in ')]}')
        if char == ',' and depth == 0:
            spans.append((begin, index))
            begin = index + 1
    if clean[begin:end].strip():
        spans.append((begin, end))
    return spans


def _empty_prototype(clean, part, callee):
    return re.search(rf'(?m)^[^\n;{{}}()]*\b{re.escape(callee)}\s*\(\s*\)\s*;', clean[:part.opening]) is not None


def _stray_drops(source, part, pointers, params):
    """Edits that remove each call's trailing local-pointer argument, when its callee takes no declared parameters."""
    clean = part.clean
    edits = []
    for hit in CALL.finditer(clean, part.opening + 1, part.end):
        callee = hit['f']
        if callee in ('if', 'while', 'for', 'switch', 'return', 'sizeof') or not _empty_prototype(clean, part, callee):
            continue
        end = close(clean, hit.end() - 1, '(', ')')
        if not end:
            continue
        spans = _arguments(clean, hit.end(), end - 1)
        if len(spans) < 2:
            continue
        last = clean[spans[-1][0]:spans[-1][1]].strip()
        if last in pointers and last not in params:
            edits.append((spans[-2][1], spans[-1][1], ''))
    return edits


def _statements(part, local):
    """The plain `local = expr;` statements, as (start, end, depth, block_start, block_end)."""
    clean = part.clean
    found = []
    for hit in re.finditer(rf'(?m)^[ \t]*({re.escape(local)})[ \t]*=(?!=)([^;{{}}]*);[ \t]*$', clean[:part.end]):
        if hit.start() <= part.opening:
            continue
        found.append(hit)
    return found


def _enclosing_block(clean, part, position):
    depth, index = 0, position
    while index > part.opening:
        index -= 1
        if clean[index] == '}':
            depth += 1
        elif clean[index] == '{':
            if depth == 0:
                return index, close(clean, index, '{', '}')
            depth -= 1
    return part.opening, part.end


def _splits(source, part, pointers, declarations):
    """One edit list per pointer local that two plain statements of one block assign: the second one's span renamed."""
    clean = part.clean
    result = []
    for local in sorted(pointers):
        sets = _statements(part, local)
        for first, second in zip(sets, sets[1:]):
            block = _enclosing_block(clean, part, second.start())
            if _enclosing_block(clean, part, first.start()) != block or not block[1]:
                continue
            if re.search(rf'(?<![\w.>]){re.escape(local)}\b', second[2]):
                continue
            span_start, span_end = second.start(), block[1]
            # a read outside the block would see the other value, and a mention before the first set is a stale read
            if re.search(rf'(?<![\w.>]){re.escape(local)}\b', clean[span_end:part.end]):
                continue
            if re.search(rf'(?<![\w.>]){re.escape(local)}\b', clean[max(block[0], declarations[local + ' end']):first.start()]):
                continue
            fresh = f'{local}_b1'
            while re.search(rf'\b{fresh}\b', clean):
                fresh += '_'
            edits = [(span_start + m.start(), span_start + m.end(), fresh)
                     for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[span_start:span_end])]
            if len(edits) < 2:
                continue
            indent, kind, stars = declarations[local]
            declaration_end = declarations[local + ' end']
            edits.append((declaration_end, declaration_end, f'{indent}{kind}{stars}{fresh};\n'))
            result.append(edits)
            break
    return result


def variants(source, name):
    part = view(source, name)
    if not part or UNORDERED.search(part.body):
        return []
    clean = part.clean
    params = _params(clean, part)
    declarations = {}
    for hit in POINTER_DECL.finditer(clean, part.opening + 1, part.end):
        local = hit[4]
        if local in params or local in declarations:
            continue
        declarations[local] = (hit[1], hit[2], hit[3])
        declarations[local + ' end'] = hit.end()
    pointers = {key for key in declarations if ' ' not in key}
    if not pointers:
        return []
    drops = _stray_drops(source, part, pointers, params)
    splits = _splits(source, part, pointers, declarations)
    out = []
    if drops and splits:
        for split in splits:
            # a rename inside an argument that goes is dropped with it
            kept = [e for e in split if not any(a <= e[0] and e[1] <= b for a, b, _ in drops)]
            out.append((FAMILY, edit(source, drops + kept)))
    if drops:
        out.append((DROP_FAMILY, edit(source, drops)))
    for split in splits:
        out.append((SPLIT_FAMILY, edit(source, split)))
    return list(dict.fromkeys(out))
