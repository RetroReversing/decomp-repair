"""A call's first argument copied on two paths of the switch before it, with the masked store value in its own local.

GCC 2.7.2 (KMC, `-G0 -mips3 -mgp32 -mfp32 -O2`) schedules the tail after a switch (an arm each storing a constant
through a pointer, then `store (E & 0xFFF); call(P, ...)`) as one block, and the first scheduler walks it backwards.
Two things put the tail's insns in the wrong order, and neither moves alone:

- The masked value (`andi`, a single-set pseudo that is live afterwards) is a "birthing" insn (`sched.c
  birthing_insn_p`), so it is launched right before its store and ahead of the argument move `move $a3, ...`; the
  target has the argument move first. Held in a `u16` local (`m = E & 0xFFF; *(s16 *)(..) = m;`) the insn is not
  boosted. Alone this scored 520 on the function below (the `andi` went to the top of the block).
- The argument move `move $a0, P` has a later original position than the `andi`, so at equal priority it was picked
  ahead of it, and ended up second to last where the target has it first. Copying the argument into a local that is
  set on the paths before the call (`ARG = P;`) makes that local a pseudo with several sets that cse cannot fold
  back into `P`: it is allocated to `$a0` at each set, the `move $a0, P` sits at the end of the paths (where the
  delay slots of their jumps take it) and the join block no longer has it. Four sets scored 115: every row of the
  block was right and the allocation swapped two saved registers.
- Every set is another reference to `P`, and `floor_log2 (refs) * refs / live` ranks `P` (a pointer stored through in
  every arm) above the record pointer it was allocated after. Two sets kept the ranking (0); three or four did not
  (115). So the copy is set in one arm and at a label the other arms reach: the arms but one `goto` that label (the
  last one just falls into it) and a `default:` there sets it for the paths with no arm.

Found on a 150-instruction KMC N64 effect spawner (the first argument `temp_s2`, four paths, the store `(s16) (v &
0xFFF)` before `func_80060890(...)`): saved best 60, the local alone 520, the copy with four sets 115, the combination
with two sets 0 (the judge's 0 and the app's compile verdict). The ready-list reading and `birthing_insn_p` are from
the compiler's `sched.c`; that the `u16` local unboosts the `andi` and that the `$a0` move is what changes the order
is read from the `-dS` traces and one function's result, so a hypothesis for other shapes. A candidate: the judge
decides.

Offered when a `switch` without `default` whose arms each end in `break;` (and hold no other jump) is followed, with
no other call between, by one call whose first argument is a pointer local stored through in at least two arms, and
a `(s16)`/`u16` store of `(E & MASK)` sits between them: one child per choice of the arm that sets the copy itself.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'arm_argument_copy_join'
FAMILIES = (FAMILY,)
COPY = 'arg_copy'
MASK = 'mask_value'
JOIN = 'arg_join'
MAX_ARMS = 6
KEYWORDS = {'sizeof', 'switch', 'if', 'for', 'while', 'return', 'do', 'case', 'default', 'goto', 'break', 'continue'}
LABEL = re.compile(r'\b(?:case\b[^:;{}]*|default)\s*:(?!:)')
CALL = re.compile(rf'\b(?P<callee>{IDENT})\s*\(\s*(?P<arg>{IDENT})\s*(?=[,)])')
STORE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<lhs>\(?\s*\*\s*\(\s*(?:s16|u16)\s*\*\s*\)[^;=]*?)=\s*(?:\(\s*(?:s16|u16)\s*\)\s*)?'
    rf'\(\s*(?P<value>[^;()=]*?&\s*{NUMBER})\s*\)\s*;')
DECLARATION = re.compile(rf'^[ \t]*(?:{IDENT}[ \t]+)+\**[ \t]*{IDENT}(?:\[\d+\])?[ \t]*(?:=[^;()]*)?;[ \t]*$')


def _pointer_type(clean, name):
    found = re.search(rf'(?m)^[ \t]*(?P<type>(?:{IDENT}[ \t]+)*{IDENT}[ \t]*\*+)[ \t]*{re.escape(name)}[ \t]*;', clean)
    if not found:
        return None
    base, stars = re.fullmatch(r'(.*?)\s*(\*+)', found['type'], re.S).groups()
    return f"{re.sub(r'[ \t]+', ' ', base)} {stars}"


def _after_declarations(clean, part):
    """The offset just after the last leading declaration line of the function body."""
    position, last = part.opening + 1, part.opening + 1
    for line in clean[part.opening + 1:part.end].splitlines(keepends=True):
        text = line.strip()
        if text and not DECLARATION.match(line.rstrip('\n')):
            break
        position += len(line)
        if text:
            last = position
    return last


def _arms(clean, start, end):
    """(label, body start, final `break;` start, its end) of every arm of the switch body clean[start:end], or None
    when there is a `default`, fewer than two or more than MAX_ARMS arms, or an arm has a jump other than its one
    final `break;`."""
    labels, depth, position = [], 0, start
    while position < end:
        char = clean[position]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif depth == 0:
            found = LABEL.match(clean, position)
            if found:
                labels.append((found.start(), found.end()))
                position = found.end()
                continue
        position += 1
    if not 2 <= len(labels) <= MAX_ARMS or clean[start:labels[0][0]].strip():
        return None
    arms = []
    for index, (label, body) in enumerate(labels):
        stop = labels[index + 1][0] if index + 1 < len(labels) else end
        text = clean[body:stop]
        tail = re.search(r'\bbreak\s*;(?=\s*$)', text)
        if clean[label:body].lstrip().startswith('default') or not tail:
            return None
        if len(re.findall(r'\b(?:break|continue|return|goto)\b', text)) != 1:
            return None
        arms.append((label, body, body + tail.start(), body + tail.end()))
    return arms


def _shape(source, name):
    """(part, arms, the call, the store) of the one switch this applies to, or None."""
    part = view(source, name)
    if not part or re.search(rf'\b(?:{COPY}|{MASK}|{JOIN})\b', source) or re.search(r'\bgoto\b|^\s*#', part.clean, re.M):
        return None
    clean = part.clean
    for hit in re.finditer(r'\bswitch\s*\(', clean[part.opening:part.end]):
        after = close(clean, part.opening + hit.end() - 1)
        brace = re.compile(r'\s*\{').match(clean, after) if after else None
        end = close(clean, brace.end() - 1, '{', '}') if brace else None
        if not end:
            continue
        arms = _arms(clean, brace.end(), end - 1)
        call = CALL.search(clean, end, part.end)
        if not arms or not call:
            continue
        window = clean[end:call.start()]
        if (any(word not in KEYWORDS for word in re.findall(rf'\b({IDENT})\s*\(', window))
                or re.search(r'\b(?:switch|if|for|while|return|goto|case|do)\b', window)
                or window.count('}') > window.count('{')):
            continue
        pointer = call['arg']
        stored = [arm for arm in arms if re.search(rf'\b{re.escape(pointer)}\b', clean[arm[1]:arm[2]])]
        stores = list(STORE.finditer(clean, end, call.start()))
        if len(stored) >= 2 and len(stores) == 1 and _pointer_type(clean[part.opening:part.end], pointer):
            return part, arms, call, stores[0]
    return None


def variants(source, name):
    shape = _shape(source, name)
    if not shape:
        return []
    part, arms, call, store = shape
    pointer = call['arg']
    kind = _pointer_type(part.clean[part.opening:part.end], pointer)
    last = len(arms) - 1
    pad = re.search(r'[ \t]*$', part.clean[:arms[0][0]])[0]
    found = []
    for own in range(len(arms)):
        edits = []
        for index, (_label, _body, stop, after) in enumerate(arms):
            if index == own:
                edits.append((stop, after, f'{COPY} = {pointer};\n{pad}    break;'))
            elif index == last:
                gap = len(part.clean[:stop].rstrip())
                edits.append((gap, after, ''))
            else:
                edits.append((stop, after, f'goto {JOIN};'))
        edits.append((arms[last][3], arms[last][3], f'\n{pad}default:\n{pad}{JOIN}: {COPY} = {pointer};\n'))
        edits.append((call.start('arg'), call.end('arg'), COPY))
        edits.append((store.start(), store.end(), f"{store['indent']}{MASK} = {store['value']};\n"
                                                  f"{store['indent']}{store['lhs'].rstrip()} = {MASK};"))
        at = _after_declarations(part.clean, part)
        edits.append((at, at, f'    {kind}{COPY};\n    u16 {MASK};\n'))
        found.append((FAMILY, edit(source, sorted(edits))))
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
