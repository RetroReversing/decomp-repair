"""A `switch` whose arms `goto` labels that sit after it, each label's run copied into the arms that jump to it.

m2c writes a switch whose arms assign what a later call needs and then jump to a label after the switch, where the
call is made once:

    switch (k) { case 0: a = 0xA; goto lookup; case 1: v = f(0x2E2); goto format; default: a = 0x2E4; goto lookup; }
    lookup: v = f(a); format: g(p, v); rest();

because the compiler's cross-jumping had merged the arms' tails. The game wrote the call in each arm
(`case 1: g(p, f(0x2E2)); break;`) and the compiler merged them again; written as one shared tail the arms' arguments
are phi variables that live across the join, each a pseudo of its own whose references change the allocator's order
and whose last copy into an argument register differs from the arms' own. A KMC GCC 2.7.2 N64 menu function
(335 instructions) had exactly this ladder around a four-way `switch`, wrapped in a `do { } while (0)` an earlier
agent added, and no family reached the arms' own calls: `goto_join_argument_copy` and the join-tail families copy a
tail into `if` arms, not into `switch` arms that reach it through labels.

`variants` takes each block that holds a `switch` followed, at the same level, by labelled statements, and for each
`goto L;` in the switch writes the run from `L:` up to the last statement that still names a variable the switch or the
run assigns, followed by `break;`; the labelled run is then removed and the statements after it stay after the
switch. The labels' run must be reached only by those gotos. One child per such `switch` (the arms are only right together)."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'switch_goto_tail_arms'
FAMILIES = (FAMILY,)
_LABEL = re.compile(rf'^\s*(?P<label>{IDENT})\s*:(?!:)')
_NOT_LABELS = {'default', 'case'}


def _close(clean, opening, pair='{}'):
    depth = 0
    for index in range(opening, len(clean)):
        depth += (clean[index] == pair[0]) - (clean[index] == pair[1])
        if depth == 0:
            return index
    return -1


def _statements(clean, start, end):
    """[(start, end)] of the statements of the block text clean[start:end] (compound ones with their `else` chain)."""
    out, index = [], start
    while index < end:
        while index < end and clean[index].isspace():
            index += 1
        if index >= end:
            break
        begin, depth = index, 0
        while index < end:
            char = clean[index]
            if char in '({':
                depth += 1
            elif char in ')}':
                depth -= 1
                if depth == 0 and char == '}':
                    rest = clean[index + 1:end].lstrip()
                    head = re.match(r'(?:else\b|while\b)', rest)
                    block_head = re.match(r'(?:if|for|while|switch|do)\b|else\b', clean[begin:index].lstrip()) \
                        or clean[begin:index].lstrip().startswith('{')
                    if head and head.group(0).startswith('else') and block_head:
                        index += 1
                        continue
                    if re.match(r'\s*do\b', clean[begin:begin + 8]) and head and head.group(0) == 'while':
                        index = clean.index(';', index) + 1
                        break
                    if block_head or not clean[begin:index].strip():
                        index += 1
                        break
            elif char == ';' and depth == 0:
                index += 1
                break
            index += 1
        out.append((begin, index))
    return out


def _assigned(text):
    return set(re.findall(rf'(?<![\w.>])({IDENT})\s*=(?!=)', text))


def _blocks(clean, start, end):
    """Every `{..}` span nested in clean[start:end], outermost first, as (open, close)."""
    found = []
    for hit in re.finditer(r'{', clean[start:end]):
        opening = start + hit.start()
        found.append((opening, _close(clean, opening)))
    return found


def _inline_arm(text):
    """The arm's `x = e;` temporaries that one later statement of the same arm reads, written into that statement."""
    changed = True
    while changed:
        changed = False
        for hit in re.finditer(rf'(?<![\w.>])(?P<x>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}]+);', text):
            x, expr = hit['x'], hit['e'].strip()
            rest = text[hit.end():]
            stop = re.search(r'\bbreak\s*;', rest)
            span = rest[:stop.start()] if stop else rest
            uses = re.findall(rf'(?<![\w.>]){re.escape(x)}\b', span)
            if len(uses) != 1 or re.search(rf'(?<![\w.>]){re.escape(x)}\s*=(?!=)', span) \
                    or set(re.findall(IDENT, expr)) & _assigned(span):
                continue
            use = re.search(rf'(?<![\w.>]){re.escape(x)}\b', span)
            wrapped = expr if re.fullmatch(rf'{IDENT}|[&\w.]+|{IDENT}\([^()]*\)', expr) else f'({expr})'
            text = text[:hit.start()] + span[:use.start()].lstrip() + wrapped + rest[use.end():]
            changed = True
            break
    return text


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for opening, closing in [(part.opening, part.end - 1)] + _blocks(clean, part.opening + 1, part.end):
        stmts = _statements(clean, opening + 1, closing)
        for at, (s_start, s_end) in enumerate(stmts):
            if not re.match(r'switch\s*\(', clean[s_start:s_end]):
                continue
            tail = stmts[at + 1:]
            labels = {}
            for k, (a, b) in enumerate(tail):
                hit = _LABEL.match(clean[a:b])
                if hit and hit['label'] not in _NOT_LABELS:
                    labels[hit['label']] = k
            if not labels:
                continue
            body_open = clean.index('{', s_start)
            body = clean[body_open:s_end]
            gotos = re.findall(rf'\bgoto\s+({IDENT})\s*;', body)
            if not gotos or set(gotos) - set(labels):
                continue
            if any(re.search(rf'\bgoto\s+{label}\b', clean[tail[0][0]:closing]) for label in labels):
                continue
            first = min(labels[g] for g in set(gotos))
            known = _assigned(body)
            runs, end_at = {}, first
            for label in set(gotos):
                names, last = set(known), labels[label]
                for k in range(labels[label], len(tail)):
                    a, b = tail[k]
                    text = _LABEL.sub('', clean[a:b], count=1)
                    if k > labels[label] and not (set(re.findall(IDENT, text)) & names):
                        break
                    names |= _assigned(text)
                    last = k
                runs[label] = last
                end_at = max(end_at, last)
            texts = {}
            for label in set(gotos):
                pieces = []
                for k in range(labels[label], runs[label] + 1):
                    a, b = tail[k]
                    pieces.append(_LABEL.sub('', clean[a:b], count=1).strip())
                texts[label] = ' '.join(pieces) + ' break;'
            new_body = re.sub(rf'\bgoto\s+({IDENT})\s*;', lambda m, texts=texts: texts[m[1]], body)
            if new_body == body:
                continue
            drop_from = tail[first][0]
            drop_to = tail[end_at][1]
            result.append((FAMILY, edit(source, [(body_open, s_end, new_body), (drop_from, drop_to, '')])))
            inlined = re.sub(r'(?s)(?:case[^:;{}]*:|default:)(?P<arm>[^{}]*?\bbreak\s*;)',
                             lambda m: m[0][:m.start('arm') - m.start()] + _inline_arm(m['arm']), new_body)
            if inlined != new_body:
                result.append((FAMILY, edit(source, [(body_open, s_end, inlined), (tail[first][0], tail[end_at][1], '')])))
                bare = re.sub(rf'\(\s*({IDENT}\([^()]*\))\s*&\s*0xFF\s*\)', r'\1', inlined)
                if bare != inlined:  # a hypothesis: the mask m2c or an agent put on a call's result
                    result.append((FAMILY, edit(source, [(body_open, s_end, bare), (tail[first][0], tail[end_at][1], '')])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
