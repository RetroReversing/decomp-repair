"""A dead parameter reused as the loop's carrier, and the loop body's reload given a local of its own (KMC GCC 2.7.2).

An N64 voice-list function walked a chain of ids: it looked a node up by its id parameter, then looped over the chain
with a head id that m2c kept in its own local. The original had no such local: the loop's carrier *is* the parameter
(`arg0 = head;`), and the byte the body reloads after its calls (`arg0 = *(u8 *)(rec + 0x63);`, used to index a table
and for three stores) is another name. 905 -> 145 -> 0. Three things, and none of them pays off alone:

* `param_loop_carrier` (merge): a local whose first reference follows the parameter's last (the lookup's last use of the
  id), outside any loop that holds both, is renamed to the parameter. The parameter's pseudo then lives through the
  loop, so it no longer takes `$a0` by default; its first instruction is a real `move $a1,$a0`.
* the merge alone is worse by a register pair: gcc's global.c lets a conflicting lower-priority pseudo that *prefers*
  a register (the parameter prefers `$a0`) push every higher-priority pseudo it conflicts with off that register. The
  table pointer the body builds from the reloaded byte conflicts with the carrier, so it moved to `$a1`, the carrier
  to `$a2`, and the return constant to `$a1` (the score 145: only registers differ).
* `redefined_web_split` (the second half): the reload and its later uses in that block get a fresh local. The carrier is
  then dead across the block, the table pointer no longer conflicts with it, and the pointer takes `$a0` as in the
  target. The split is only offered where the variable is dead at the block's end: the first reference after the block
  is an unconditional assignment that sits inside every loop around the block.

The combined child (merge, then split) is offered as one candidate, and the split alone for any scalar the same way.
Both are candidate rewrites, not equivalence proofs: the exact judge decides. The compiler explanation (global.c's
`prune_preferences`/`regs_someone_prefers`) was read in the pinned 2.7.2 source; the exact source of the match is a
single function, so the rule is one case, not a controlled study.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, locals_for, view
from .pattern_repairs import close

FAMILY_CARRIER = 'param_loop_carrier'
FAMILY_SPLIT = 'redefined_web_split'
FAMILIES = (FAMILY_CARRIER, FAMILY_SPLIT)
LIMIT = 8

_WORD = re.compile(r'(?:u32|s32|int|unsigned(?:\s+int)?|signed(?:\s+int)?)')
_JUMPS = re.compile(r'\b(?:goto|break|continue|return|switch|case|default)\b|(?m:^[ \t]*(?!case\b|default\b)[A-Za-z_]\w*[ \t]*:(?!:))')
_WRITE = re.compile(r'\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)')


def _parameters(clean, opening, name):
    """(name, type) of each plain 32-bit integer parameter."""
    hit = re.search(rf'\b{re.escape(name)}\s*\(([^{{}};]*)\)\s*$', clean[:opening])
    if not hit:
        return {}
    found = {}
    for piece in hit[1].split(','):
        one = re.fullmatch(rf'\s*({INTEGER})\s+({IDENT})\s*', piece)
        if one and _WORD.fullmatch(re.sub(r'\s+', ' ', one[1])):
            found[one[2]] = one[1]
    return found


def _words(part, variable, lo, hi):
    return [h for h in re.finditer(rf'\b{re.escape(variable)}\b', part.clean[lo:hi])
            if not re.search(r'(?:\.|->|\bgoto)\s*$', part.clean[:lo + h.start()])
            and not re.match(r'\s*:(?!:)', part.clean[lo + h.end():lo + h.end() + 3])]


def _block_start(clean, at, lo):
    """The `{` of the innermost block holding `at` (or None at the function's own level)."""
    depth = 0
    for i in range(at - 1, lo - 1, -1):
        ch = clean[i]
        if ch == '}':
            depth += 1
        elif ch == '{':
            if depth == 0:
                return i
            depth -= 1
    return None


def _loops(part):
    """(start, end) of every loop: the keyword through its closing brace or statement."""
    clean, spans = part.clean, []
    for hit in re.finditer(r'\b(?:for|while)\s*\(|\bdo\b', clean[part.opening + 1:part.end]):
        start = part.opening + 1 + hit.start()
        if hit[0] == 'do':
            at = part.opening + 1 + hit.end()
        else:
            at = close(clean, part.opening + 1 + hit.end() - 1)
            if not at:
                continue
        rest = re.match(r'\s*', clean[at:])
        at += rest.end()
        if clean[at:at + 1] == '{':
            stop = close(clean, at, '{', '}')
        else:
            stop = clean.find(';', at) + 1
        if stop:
            spans.append((start, stop))
    return spans


def _backward_goto(clean):
    labels = {m[1]: m.start() for m in re.finditer(r'(?m)^[ \t]*(?!case\b|default\b)([A-Za-z_]\w*)[ \t]*:(?!:)', clean)}
    return any(m[1] in labels and labels[m[1]] < m.start() for m in re.finditer(r'\bgoto\s+(\w+)', clean))


def _merges(source, name):
    """(parameter, local, source with the local renamed to the parameter and its declaration gone)."""
    part = view(source, name)
    if not part or _backward_goto(part.clean) or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    params = _parameters(part.clean, part.opening, name)
    loops = _loops(part)
    result = []
    for decl in locals_for(part):
        local, kind = decl['name'], decl['type']
        if not _WORD.fullmatch(re.sub(r'\s+', ' ', kind)) or local in params:
            continue
        mine = [h for h in re.finditer(rf'\b{re.escape(local)}\b', part.clean)
                if part.opening < h.start() < part.end and not decl.start() <= h.start() < decl.end()
                and not re.search(r'(?:\.|->|\bgoto)\s*$', part.clean[:h.start()])]
        if not mine or not re.match(r'\s*=(?!=)', part.clean[mine[0].end():mine[0].end() + 3]):
            continue
        for param in params:
            if re.search(rf'&\s*{re.escape(param)}\b', part.body):
                continue
            theirs = _words(part, param, part.opening + 1, part.end)
            if not theirs or theirs[-1].start() + part.opening + 1 >= mine[0].start():
                continue
            last = [part.opening + 1 + h.start() for h in theirs]
            if any(a <= p < b and a <= m.start() < b for a, b in loops for p in last for m in mine):
                continue
            changes = [(m.start(), m.end(), param) for m in mine] + [(decl.start(), decl.end(), '')]
            result.append((param, local, edit(source, changes)))
    return result


def _splits(source, name, only=None):
    """Sources where one variable's mid-block reload and the block's later uses have a local of their own."""
    part = view(source, name)
    if not part or _backward_goto(part.clean) or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    clean = part.clean
    kinds = _parameters(clean, part.opening, name)
    kinds.update({d['name']: d['type'] for d in locals_for(part) if _WORD.fullmatch(re.sub(r'\s+', ' ', d['type']))})
    loops = _loops(part)
    result = []
    for variable, kind in kinds.items():
        if only and variable != only:
            continue
        if re.search(rf'&\s*{re.escape(variable)}\b', part.body):
            continue
        fresh = f'__repair_web_{variable}'
        if fresh in source:
            continue
        pattern = re.compile(rf'(?<![\w.>]){re.escape(variable)}\s*=(?!=)\s*([^;{{}}]+);')
        for hit in pattern.finditer(clean, part.opening + 1, part.end):
            if re.search(rf'\b{re.escape(variable)}\b', hit[1]):
                continue
            if clean[:hit.start()].rstrip()[-1:] not in ';{}':
                continue
            opening = _block_start(clean, hit.start(), part.opening)
            if opening is None or opening == part.opening:
                continue
            stop = close(clean, opening, '{', '}')
            if not stop:
                continue
            later = _words(part, variable, hit.end(), stop)
            if not later or any(_WRITE.match(clean[hit.end() + h.end():hit.end() + h.end() + 4])
                                or re.search(r'(?:\+\+|--)\s*$', clean[:hit.end() + h.start()]) for h in later):
                continue
            if _JUMPS.search(clean[hit.end():stop]):
                continue
            after = _words(part, variable, stop, part.end)
            if not after:
                continue
            nxt = stop + after[0].start()
            redefinition = pattern.match(clean, nxt)
            if (not redefinition or re.search(rf'\b{re.escape(variable)}\b', redefinition[1])
                    or clean[:nxt].rstrip()[-1:] not in ';{}' or _JUMPS.search(clean[stop:nxt])):
                continue
            above = _block_start(clean, nxt, part.opening)
            if above is not None and above != part.opening and above > opening:
                continue
            if any(a <= hit.start() < b and not a <= nxt < b for a, b in loops):
                continue
            changes = [(hit.start(), hit.start() + len(variable), fresh)]
            changes += [(hit.end() + h.start(), hit.end() + h.end(), fresh) for h in later]
            changes.append((opening + 1, opening + 1, f'\n{kind} {fresh};\n'))
            result.append(edit(source, changes))
            break
    return result


def variants(source, name):
    result = []
    for param, local, merged in _merges(source, name):
        splits = _splits(merged, name, only=param)
        result.extend((FAMILY_CARRIER, text) for text in splits)
        result.append((FAMILY_CARRIER, merged))
    result.extend((FAMILY_SPLIT, text) for text in _splits(source, name))
    return list(dict.fromkeys(result))[:LIMIT]
