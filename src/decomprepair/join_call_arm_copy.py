"""join_call_arm_copy: the call a switch's join makes, made at the end of each arm that reaches it.

m2c reads a switch whose arms each pick a value and then fall into one shared call the way the machine code reads it:

    switch (kind) { case 1: v = 0x18C; break; case 2: v = D[rand(4)]; break; default: v = 0x146; break; }
    play: update(sound(v, dist, 0xFF), table[(u16) index], p + 0x24, 0);

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) then keeps the whole tail in one block: the call's result is still in
`$v0` while the second argument (`lhu`, `sll`) is computed, so the first scheduler puts the `lhu` before the copy of
`$v0` and the index pseudo cannot take `$v0` (it lives across the call's return register): `lhu $v1` and a `move $a0,
$v0` after it, where the game had `move $a0,$v0; lhu $v0`. A 251-instruction sound-selection function sat at 210 with
exactly those four rows. The game called the sound function in each arm (`result = sound(v, dist, 0xFF); break;`), so the
result is a pseudo set in several blocks and the tail starts with the copy into the argument register and has no `$v0`
live; cross-jumping after allocation merges the identical arm tails again, so the size does not change (210 -> 0).

`join_call_arm_copy` finds the first statement after a `switch` (and the label the arms `goto`) of the form
`outer(.., inner(args), ..);` or `V = inner(args);` where `inner`'s arguments are plain variables and literals (nothing
between the arms' ends and the join can change them), and writes `join_result = inner(args);` at the end of every arm: before
each `break;` that belongs to this switch, before each `goto` to the join's label, and at the end of the switch when
its last arm falls out. The join then reads the result (or, in the `V = ..` form, loses the statement). A `switch`
with no `default:` has a path that skips every arm, so it is left alone, as is a goto to the label from outside the
switch and a `void` callee. One child per join; the judge decides. Hypothesis: the register-overlap reading above is
from the dumps of the one function and the compiler's sched.c, not a documented rule; the match confirmed the effect.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'join_call_arm_copy'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
RESULT = 'join_result'
KEYWORDS = {'switch', 'for', 'while', 'do', 'if', 'else', 'return', 'sizeof', 'case', 'default', 'goto'}
PLAIN = re.compile(r'^[\w\s,.+\-*/&|^~<>()\[\]]*$')


def _statement_end(clean, at):
    """The position of the `;` that ends the statement starting at `at` (brackets balanced), or None."""
    depth = 0
    for pos in range(at, len(clean)):
        ch = clean[pos]
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
            if depth < 0:
                return None
        elif ch == ';' and depth == 0:
            return pos
    return None


def _switches(clean, start, stop):
    """(switch keyword, opening brace, position after its closing brace) of each top-level switch of a body."""
    found = []
    depth = 0
    pos = start
    while pos < stop:
        ch = clean[pos]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        elif depth == 0 and clean.startswith('switch', pos) and not re.match(r'\w', clean[pos - 1]):
            head = re.compile(r'switch\s*\(').match(clean, pos)
            if head:
                after = close(clean, head.end() - 1, '(', ')')
                brace = re.compile(r'\s*\{').match(clean, after) if after else None
                if brace:
                    opening = brace.end() - 1
                    end = close(clean, opening, '{', '}')
                    if end:
                        found.append((pos, opening, end))
                        pos = end
                        continue
        pos += 1
    return found


def _exits(clean, opening, end, label):
    """Where each path out of the switch to its join needs the call: `break;` of this switch, `goto label;` and the
    fall-out of the last arm. None when a loop with no braces could hide a `break`, or a path cannot be placed."""
    body = clean[opening + 1:end - 1]
    if re.search(r'\b(?:for|while)\s*\(', body):
        for head in re.finditer(r'\b(?:for|while)\s*\(', body):
            after = close(body, head.end() - 1, '(', ')')
            if after is None or not re.match(r'\s*[{;]', body[after:]):
                return None
    spots = []
    stack = []  # the headers of the open braces: does a `break` here leave this switch?
    last = None
    pos = opening + 1
    while pos < end - 1:
        ch = clean[pos]
        if ch == '{':
            header = clean[max(clean.rfind(';', 0, pos), clean.rfind('{', 0, pos), clean.rfind('}', 0, pos)) + 1:pos]
            stack.append(bool(re.search(r'\b(?:switch|for|while|do)\b', header)))
        elif ch == '}':
            if stack:
                stack.pop()
        elif not re.match(r'\w', clean[pos - 1]):
            word = re.compile(r'(?:break|goto\s+(' + IDENT + r'))\s*;').match(clean, pos)
            if word:
                if word.group(1) is None and not any(stack):
                    spots.append((pos, word.end()))
                elif word.group(1) == label and label:
                    spots.append((pos, word.end()))
                pos = word.end()
                last = word.end()
                continue
        pos += 1
    tail = clean[last or opening + 1:end - 1]
    if re.search(r'\w', tail) and not re.search(r'\b(?:return|continue)\b[^;]*;\s*$', tail):
        spots.append((end - 1, end - 1))  # the last arm falls out of the switch
    return spots


def _local(clean, opening, end, var):
    return re.search(r'(?m)^[ \t]*[\w ]+?[\s*]+' + re.escape(var) + r'\s*;', clean[opening:end]) is not None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for at, brace, after in _switches(clean, opening + 1, end - 1):
        if not re.search(r'\bdefault\s*:', clean[brace:after]):
            continue
        # the join: an optional label, then one statement
        label = re.compile(r'\s*(' + IDENT + r')\s*:(?!:)').match(clean, after)
        label_name = label.group(1) if label and label.group(1) not in KEYWORDS else None
        start = label.end() if label_name else after
        stmt_at = re.compile(r'\s*').match(clean, start).end()
        stop = _statement_end(clean, stmt_at)
        if stop is None:
            continue
        statement = clean[stmt_at:stop]
        direct = re.fullmatch(r'(' + IDENT + r')\s*=(?!=)\s*(' + IDENT + r'\s*\((?P<a>[^;{}]*)\))\s*', statement)
        inner = None
        if direct and direct.group(1) not in KEYWORDS and _local(clean, opening, end, direct.group(1)):
            inner = (stmt_at + direct.start(2), stmt_at + direct.end(2), direct.group(1))
        else:
            outer = re.match(r'(' + IDENT + r')\s*\(', statement)
            if outer and outer.group(1) not in KEYWORDS:
                for call in re.finditer(r'(?<![\w.>])(' + IDENT + r')\s*\(', statement):
                    if call.start() == 0 or call.group(1) in KEYWORDS:
                        continue
                    close_at = close(statement, call.end() - 1, '(', ')')
                    if close_at and statement[:call.start()].count('(') - statement[:call.start()].count(')') == 1:
                        inner = (stmt_at + call.start(), stmt_at + close_at, None)
                        break
        if not inner:
            continue
        call_text = source[inner[0]:inner[1]]
        callee = re.match(IDENT, call_text).group()
        args = call_text[call_text.index('(') + 1:call_text.rindex(')')]
        if not PLAIN.match(args) or re.search(IDENT + r'\s*\(', args):
            continue
        kind = re.search(r'(?m)^[ \t]*(?:extern\s+)?([A-Za-z_][\w \t*]*?)[ \t*]*\b' + callee + r'\s*\(', clean[:opening])
        ctype = (kind.group(1).strip() if kind else 's32') or 's32'
        if re.fullmatch(r'void', ctype):
            continue
        spots = _exits(clean, brace, after, label_name)
        if not spots:
            continue
        gotos = [m for m in re.finditer(r'\bgoto\s+' + re.escape(label_name) + r'\s*;', clean)] if label_name else []
        if any(not brace < g.start() < after for g in gotos):
            continue
        target = inner[2] or RESULT
        if inner[2] is None and re.search(r'\b' + RESULT + r'\b', source):
            continue
        text = source
        edits = []
        for lo, hi in spots:
            piece = source[lo:hi] if hi > lo else ''
            edits.append((lo, hi, '{ ' + target + ' = ' + call_text + '; ' + piece + ' }'))
        if inner[2] is None:
            edits.append((inner[0], inner[1], RESULT))
        else:
            line_start = source.rfind('\n', 0, stmt_at) + 1
            line_end = source.find('\n', stop) + 1 or len(source)
            edits.append((line_start, line_end, ''))
        for lo, hi, new in sorted(edits, key=lambda e: -e[0]):
            text = text[:lo] + new + text[hi:]
        if inner[2] is None:
            line = source.find('\n', opening) + 1
            text = text[:line] + '    ' + ctype + ' ' + RESULT + ';\n' + text[line:]
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result[:2]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
