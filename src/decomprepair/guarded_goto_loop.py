"""A backward `goto` loop whose test sits inside a guard, written as the `do { } while` it came from.

m2c ends a command interpreter's loop as `L: ...; if (!(r & 0xFF)) { t = n + 1; n = t; if ((t & 0xFF) < 0x21U) {
goto L; } }`. GCC 2.x's loop pass only sees loops the front end made (`do`, `while`, `for`), so a goto loop's invariants
stay where they are used, once per pass. In a 1315-instruction KMC GCC 2.7.2 sound-sequence interpreter
(`-G0 -mips3 -mgp32 -mfp32 -O2`) the target holds `-1` and the reciprocal of `/ 100` (`0x51EB851F`) in saved registers
before its loop; the goto loop computes them in each arm. An earlier search had imitated the hoist with locals set
before the label (`divisor = 0x51EB851F`), which a real loop does not need: as a `do { } while` with literals the
interpreter went 22323 -> 19185, its two cached constants included. `goto_loop_invariants` writes the plain
`if (c) goto L;` loop, but not one whose body holds a `switch` (its `break`s), or whose test is guarded.

`guarded_goto_loop`
    The one `goto L;` after label `L:` that ends the label's block, either as `if (B) goto L;` or as the last
    statement of `if (A) { S if (B) goto L; }` (braces optional), becomes `do { BODY if (!(A)) break; S } while (B);`
    (`do { BODY } while (B);` without a guard). The body may hold `switch` statements and loops (their `break`s stay
    theirs) but no other `break` or any `continue`. Children: the loop alone, and the loop with each local assigned
    a literal just before the label and only read in the loop written as that literal at its uses.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_goto_loop'
FAMILIES = (FAMILY,)


def _enclosed(text, at):
    """Whether position `at` of `text` sits inside a `switch`, `for`, `while` or `do` block opened within `text`."""
    depth = 0
    pos = at
    while pos > 0:
        pos -= 1
        char = text[pos]
        if char == '}':
            depth += 1
        elif char == '{':
            if depth:
                depth -= 1
                continue
            head = text[:pos].rstrip()
            if head.endswith('do') and not re.search(r'\w', head[-3:-2] or ' '):
                return True
            if head.endswith(')'):
                depth_p = 0
                for back in range(len(head) - 1, -1, -1):
                    depth_p += (head[back] == ')') - (head[back] == '(')
                    if depth_p == 0:
                        if re.search(r'\b(?:switch|for|while)\s*$', head[:back]):
                            return True
                        break
    return False


def _controlled(text):
    """True when every `break` in `text` belongs to a construct inside it and there is no `continue`."""
    if re.search(r'\bcontinue\b', text):
        return False
    return all(_enclosed(text, hit.start()) for hit in re.finditer(r'\bbreak\b', text))


def _inner(clean, start, stop, label):
    """(if start, condition, statement end) of `if (B) [{] goto L; [}]` ending just before `stop`."""
    for hit in re.finditer(r'\bif\s*\(', clean[start:stop]):
        at = start + hit.start()
        paren = start + hit.end() - 1
        after = close(clean, paren, '(', ')')
        if not after:
            continue
        tail = re.match(r'\s*(\{\s*)?goto\s+' + re.escape(label) + r'\s*;\s*(\})?', clean[after:stop])
        if not tail or bool(tail[1]) != bool(tail[2]) or clean[after + tail.end():stop].strip():
            continue
        return at, clean[paren + 1:after - 1], after + tail.end()
    return None


def _loops(part):
    clean = part.clean
    found = []
    for label in re.finditer(r'(?m)^[ \t]*(' + IDENT + r')\s*:(?!:)', clean[part.opening:part.end]):
        name = label[1]
        if name == 'default':
            continue
        label_start = part.opening + label.start()
        label_end = part.opening + label.end()
        gotos = [g for g in re.finditer(r'\bgoto\s+' + re.escape(name) + r'\s*;', clean[part.opening:part.end])]
        if len(gotos) != 1 or part.opening + gotos[0].start() < label_end:
            continue
        goto = part.opening + gotos[0].start()
        # the label's block: the innermost `{` before the label that is still open
        depth = 0
        block = None
        for pos in range(label_start - 1, part.opening - 1, -1):
            if clean[pos] == '}':
                depth += 1
            elif clean[pos] == '{':
                if depth == 0:
                    block = pos
                    break
                depth -= 1
        block_end = close(clean, block, '{', '}') if block is not None else None
        if not block_end or goto > block_end:
            continue
        # the guard: the outermost `if (A) {` at the label's depth that contains the goto, if any
        guard = None
        depth = 0
        statement_end = None
        pos = label_end
        while pos < block_end - 1:
            char = clean[pos]
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
            elif depth == 0 and clean.startswith('if', pos) and not re.match(r'\w', clean[pos - 1]) and re.match(
                    r'if\s*\(', clean[pos:]):
                paren = clean.index('(', pos)
                after = close(clean, paren, '(', ')')
                brace = re.match(r'\s*\{', clean[after:]) if after else None
                if brace:
                    opening = after + brace.end() - 1
                    closing = close(clean, opening, '{', '}')
                    if closing and opening < goto < closing:
                        guard = (pos, clean[paren + 1:after - 1], opening, closing)
                        statement_end = closing
                        break
                if after and goto > after:
                    simple = re.match(r'\s*goto\s+' + re.escape(name) + r'\s*;', clean[after:])
                    if simple and after + simple.end() > goto:
                        statement_end = after + simple.end()
                        guard = None
                        break
            pos += 1
        if statement_end is None:
            continue
        if re.search(r'^\s*else\b', clean[statement_end:]):
            continue
        if guard:
            inner = _inner(clean, guard[2] + 1, guard[3] - 1, name)
            if not inner:
                continue
            body = (label_end, guard[0])
            middle = (guard[2] + 1, inner[0])
            condition = inner[1]
            if not _controlled(clean[middle[0]:middle[1]]):
                continue
        else:
            inner = _inner(clean, label_end, statement_end, name)
            if not inner:
                continue
            body = (label_end, inner[0])
            middle = None
            condition = inner[1]
        if not _controlled(clean[body[0]:body[1]]):
            continue
        found.append({'label': (label_start, label_end), 'name': name, 'body': body, 'guard': guard,
                      'middle': middle, 'condition': condition, 'end': statement_end})
    return found


def _literal_stages(part, loop):
    """`name = LITERAL;` statements just before the label, for locals only the loop reads."""
    clean = part.clean
    before = clean[part.opening + 1:loop['label'][0]]
    stages = []
    for hit in reversed(list(re.finditer(r'(?m)^[ \t]*(' + IDENT + r')\s*=\s*(-?\s*' + NUMBER + r')\s*;[ \t]*\n?', before))):
        if before[hit.end():].strip() and (not stages or before[hit.end():stages[-1][0].start()].strip()):
            break
        stages.append((hit, hit[1], re.sub(r'\s+', '', hit[2])))
    found = []
    inside = clean[loop['label'][1]:loop['end']]
    for hit, name, value in stages:
        uses = [m for m in re.finditer(r'\b' + re.escape(name) + r'\b', clean[part.opening:part.end])]
        declared = re.search(r'\b\w+[\s*]+' + re.escape(name) + r'\s*;', clean[part.opening:part.end])
        inside_uses = list(re.finditer(r'\b' + re.escape(name) + r'\b', inside))
        if not inside_uses or len(uses) != len(inside_uses) + 1 + bool(declared):
            continue
        if re.search(r'\b' + re.escape(name) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*' + re.escape(name)
                     + r'\b|\b' + re.escape(name) + r'\s*(?:\+\+|--)|&\s*' + re.escape(name) + r'\b', inside):
            continue
        found.append((part.opening + 1 + hit.start(), part.opening + 1 + hit.end(), name, value, declared))
    return found


def _rewrite(source, part, loop):
    edits = [(loop['label'][0], loop['label'][1], 'do {')]
    condition = loop['condition'].strip()
    if loop['guard']:
        guard_start, guard_condition, opening, _ = loop['guard']
        test = guard_condition.strip()
        negated = re.fullmatch(r'!\s*(\(.*\))', test, re.S)
        if negated and close(negated[1], 0, '(', ')') == len(negated[1]):
            test = negated[1][1:-1].strip()
        else:
            test = f'!({test})'
        edits.append((guard_start, opening + 1, f'if ({test})\n      break;\n'))
        edits.append((loop['middle'][1], loop['end'], f'}} while ({condition});'))
    else:
        edits.append((loop['body'][1], loop['end'], f'}} while ({condition});'))
    return edit(source, edits)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    results = []
    for loop in _loops(part):
        results.append((FAMILY, _rewrite(source, part, loop)))
        stages = _literal_stages(part, loop)
        if not stages:
            continue
        edits = []
        for start, stop, local, value, declared in stages:
            edits.append((start, stop, ''))
            for use in re.finditer(r'\b' + re.escape(local) + r'\b', part.clean[loop['label'][1]:loop['end']]):
                at = loop['label'][1] + use.start()
                edits.append((at, at + len(local), f'({value})' if value.startswith('-') else value))
            if declared:
                at = part.opening + declared.start()
                edits.append((at, at + re.match(r'[^;]*;', source[at:]).end(), ''))
        staged = edit(source, edits)
        again = view(staged, name)
        for other in _loops(again) if again else []:
            if other['name'] == loop['name']:
                results.append((FAMILY, _rewrite(staged, again, other)))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
