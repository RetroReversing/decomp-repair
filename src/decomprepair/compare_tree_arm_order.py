"""A large switch's arms laid out in the order of the blocks the target's compare tree jumps to.

    switch (state) { case 0x16: ...; break; case 0x17: ...; break; case 0x1A: ...; break; case 0x1B: ...; break; }

GCC 2.7.2 puts the arms of a switch in the source's order, and a sparse switch has no jump table to read the order from:
it is a tree of `beq`/`slti` on the selector. `switch_case_order` permutes small switches (four arms); a state machine of
twenty arms was exact only with its arms in the target's block order (1450 -> 300, one move of two arms past four), which
neither it nor `target_switch_order` (jump tables only) offers.

The order is read from the target: for each case value the compare tree is run from its first compare with that value in
the selector register, and the first instruction that is not part of the dispatch (no compare of the selector, no
constant load, no branch) is where the arm starts. Arms are then sorted by that position. An arm whose code is empty
(`case 0: break;`) lands outside the switch and emits no code, so it stays where it was. Whole groups move together
(stacked labels and fall-through), and every group must end in `break`, `return`, `continue` or `goto`. A candidate
rewrite; the exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'compare_tree_arm_order'
FAMILIES = (FAMILY,)

_LABEL = re.compile(r"\bcase\s+(-?(?:0[xX][0-9a-fA-F]+|\d+))[uUlL]*\s*:|\bdefault\s*:")
_REG = r'\$(\w+)'
_NUM = r'(-?(?:0[xX][0-9a-fA-F]+|\d+))'
_LI = re.compile(rf'(?:addiu|ori)\s+{_REG},\s*\$zero,\s*{_NUM}$|li\s+{_REG},\s*{_NUM}$')
_SLTI = re.compile(rf'(slti|sltiu)\s+{_REG},\s*{_REG},\s*{_NUM}$')
_BEQ = re.compile(rf'(beq|bne)l?\s+{_REG},\s*{_REG},\s*([\w.$]+)$')
_BZ = re.compile(rf'(beqz|bnez|blez|bgtz|bltz|bgez)l?\s+{_REG},\s*([\w.$]+)$')
_JUMP = re.compile(r'(?:j|b)\s+([\w.$]+)$')


def _rows(asm):
    """([instruction text], {label: index of the instruction it names})."""
    rows, labels = [], {}
    for line in asm.splitlines():
        text = re.sub(r'/\*.*?\*/', '', line).split('#', 1)[0].strip()
        if not text:
            continue
        mark = re.fullmatch(r'([.\w$]+):', text)
        if mark:
            labels[mark[1]] = len(rows)
        elif not re.match(r'(?:glabel|endlabel|\.\w+\s)', text):
            rows.append(' '.join(text.split()))
    return rows, labels


def _number(text):
    return int(text, 0)


def _land(rows, labels, start, selector, value):
    """The instruction index the dispatch reaches for `value` in `selector`, or None."""
    registers = {selector: value, 'zero': 0}
    at = start
    for _ in range(200):
        if not 0 <= at < len(rows):
            return None
        row = rows[at]
        target = None
        taken = False
        if (hit := _LI.match(row)):
            registers[hit[1] or hit[3]] = _number(hit[2] or hit[4])
            at += 1
            continue
        if (hit := _SLTI.match(row)) and hit[3] == selector:
            limit = _number(hit[4])
            number = value & 0xFFFFFFFF if hit[1] == 'sltiu' else value
            registers[hit[2]] = int(number < (limit & 0xFFFFFFFF if hit[1] == 'sltiu' else limit))
            at += 1
            continue
        if row == 'nop':
            at += 1
            continue
        if (hit := _BEQ.match(row)):
            if hit[2] not in registers or hit[3] not in registers:
                return None
            taken = (registers[hit[2]] == registers[hit[3]]) == (hit[1] == 'beq')
            target = hit[4]
        elif (hit := _BZ.match(row)):
            if hit[2] not in registers:
                return None
            x = registers[hit[2]]
            taken = {'beqz': x == 0, 'bnez': x != 0, 'blez': x <= 0, 'bgtz': x > 0, 'bltz': x < 0, 'bgez': x >= 0}[hit[1]]
            target = hit[3]
        elif (hit := _JUMP.match(row)):
            taken, target = True, hit[1]
        else:
            return at
        # the delay slot runs with the branch; only constants and compares of the selector matter to the dispatch
        slot = rows[at + 1] if at + 1 < len(rows) else 'nop'
        likely = row.split()[0].endswith('l')
        if taken or not likely:
            if (li := _LI.match(slot)):
                registers[li[1] or li[3]] = _number(li[2] or li[4])
            elif (cmp := _SLTI.match(slot)) and cmp[3] == selector:
                registers[cmp[2]] = int(value < _number(cmp[4]))
        if taken:
            if target not in labels:
                return None
            at = labels[target]
            # code past the dispatch is the arm itself; a jump target that is not dispatch ends the walk at once
        else:
            at += 2
    return None


def _dispatches(rows):
    """(start index, selector register) of every compare tree that could dispatch a switch."""
    out = []
    for i, row in enumerate(rows[:-1]):
        hit = _BEQ.match(row)
        if not hit or not i:
            continue
        constant = _LI.match(rows[i - 1])
        if not constant:
            continue
        register = constant[1] or constant[3]
        selector = hit[3] if hit[2] == register else hit[2] if hit[3] == register else None
        slot = _SLTI.match(rows[i + 1])
        if selector and slot and slot[3] == selector:
            out.append((i - 1, selector))
    return out[:4]


def _groups(source, clean, brace, end):
    """[(start, stop, values)] of the switch body's groups, or None when a group could not be moved."""
    labels = [m for m in _LABEL.finditer(source, brace + 1, end - 1)
              if clean[brace + 1:m.start()].count('{') == clean[brace + 1:m.start()].count('}')
              and clean[m.start():m.start() + 4] in ('case', 'defa')]
    inside = clean[brace + 1:end - 1]
    every = [m for m in re.finditer(r'\b(?:case|default)\b', inside)
             if inside[:m.start()].count('{') == inside[:m.start()].count('}')]
    if len(labels) != len(every) or not 3 <= len(labels) <= 256 or clean[brace + 1:labels[0].start()].strip():
        return None
    groups, start, values = [], labels[0].start(), []
    for i, label in enumerate(labels):
        stop = labels[i + 1].start() if i + 1 < len(labels) else end - 1
        if label[1] is not None:
            values.append(_number(label[1]))
        body = clean[label.end():stop].strip()
        if not body:
            continue
        terminal = re.search(r'\b(?:goto\s+\w+|break|continue|return(?:\s+[^;{}]+)?)\s*;\s*\}?\s*$', body)
        prefix = body[:terminal.start()].rstrip() if terminal else ''
        if terminal and (not prefix or prefix[-1] in ';{}') and body.count('{') == body.count('}'):
            groups.append((start, stop, values, body))
            start, values = stop, []
    if start != end - 1 or len(groups) < 3:
        return None
    for a, b, _, _ in groups:  # a declaration at the switch's own depth would change scope
        for hit in re.finditer(r'\b(?:char|int|short|long|float|double|[su]\d+)\s+\**\w+\s*(?:[=;\[])', clean[a:b]):
            if clean[a:a + hit.start()].count('{') == clean[a:a + hit.start()].count('}'):
                return None
    return groups


def variants(source, name, asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    rows, labels = _rows(asm)
    dispatches = _dispatches(rows)
    if not dispatches:
        return []
    clean = _blank(source)
    out = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[span[0]:span[1]]):
        cond = close(clean, span[0] + switch.end() - 1)
        if not cond:
            continue
        brace = cond + len(clean[cond:]) - len(clean[cond:].lstrip())
        if clean[brace:brace + 1] != '{' or not (end := close(clean, brace, '{', '}')):
            continue
        groups = _groups(source, clean, brace, end)
        if not groups:
            continue
        for start, selector in dispatches:
            places = []
            for _, _, values, body in groups:
                if not values or re.fullmatch(r'break\s*;', body):
                    places.append(None)
                    continue
                reached = [_land(rows, labels, start, selector, value) for value in values]
                places.append(None if None in reached else min(reached))
            placed = [p for p in places if p is not None]
            if len(placed) < 3 or len(set(placed)) != len(placed):
                continue  # arms sharing a landing means this is not their dispatch
            movable = iter(sorted((i for i, p in enumerate(places) if p is not None), key=places.__getitem__))
            order = [next(movable) if p is not None else i for i, p in enumerate(places)]
            if order == list(range(len(groups))):
                continue
            # keep each group's own text; the closing text of the last one moves with its position
            texts = [source[a:b].rstrip() for a, b, _, _ in groups]
            gaps = [source[a + len(source[a:b].rstrip()):b] for a, b, _, _ in groups]
            body = ''.join(texts[j] + gaps[i] for i, j in enumerate(order))
            out.append((FAMILY, source[:groups[0][0]] + body + source[groups[-1][1]:]))
    return list(dict.fromkeys(out))[:3]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
