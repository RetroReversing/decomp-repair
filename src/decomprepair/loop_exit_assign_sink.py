"""A copy at the head of a loop, ahead of its exit test, written once after the loop.

A walker that keeps a second cursor up to date can state the copy at the head of every pass:

    for (;;) {                                  for (;;) {
        next = (u8 *) cursor;                       if (k >= n) goto done;
        if (k >= n) goto done;                      ... /* never names `next` */
        ... /* never names `next` */    ->      }
    }                                           done:
    done:                                       next = (u8 *) cursor;

Nothing in the loop reads the copy, so only its value on the way out matters. The compiled difference is the copy's
life: written in the loop it is set on every pass and the pointer it feeds is live around the loop, which can keep a
later `p = hdr + 8; q = p;` from being folded into one add. Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 mesh
walker of 209 instructions: 660 -> 350 with the copy moved after the loop (the header advance `addiu $v1, $v0, 8;
move $t3, $v1` came out). The register account is a hypothesis from the two objects; the exact judge decides.

loop_exit_assign_sink
    `X = E;` as the first statement of a `for (;;)`/`while (1)` body, followed by its exit test (`goto L;` to the label
    right after the loop, or `break;`), written after the loop instead. X is a plain local whose address is never taken
    and which neither the test nor the rest of the loop names; E is a name, possibly cast and offset by a number; the
    test has no side effect; the rest of the loop leaves it by no other way.
"""
import re

from .c_scan import close
from .integer_repair_support import edit, view

FAMILY = 'loop_exit_assign_sink'
FAMILIES = (FAMILY,)
LIMIT = 6
_LOOP = re.compile(r'\b(?:for\s*\(\s*;\s*;\s*\)|while\s*\(\s*1\s*\))\s*\{')
_HEAD = re.compile(r'\s*(?P<name>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<value>[^;=]+);\s*if\s*\(')
_VALUE = re.compile(r'(?:\(\s*[A-Za-z_][\w\s]*\**\s*\)\s*)*[A-Za-z_]\w*(?:\s*[+-]\s*(?:0x[0-9A-Fa-f]+|\d+))?\s*\Z')
_EXIT = re.compile(r'\s*(?P<open>\{\s*)?(?:goto\s+(?P<label>[A-Za-z_]\w*)|(?P<brk>break))\s*;(?(open)\s*\})')
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|[A-Za-z_]\w*\s*\((?!\s*\*)')


def _local(body, name):
    """Is `name` declared in the function's body, with its address never taken?"""
    declared = re.search(rf'(?m)(?:^|[;{{])\s*(?!return\b|goto\b)[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*[\s*]+{name}\s*[;,\[=]',
                         body)
    return bool(declared) and not re.search(rf'(?<![&\w])&\s*{name}\b', body)


def _other_exit(rest):
    """Does the loop's remaining body leave the loop (a return, a break of its own, a goto to a label outside it)?"""
    if re.search(r'\breturn\b', rest):
        return True
    labels = set(re.findall(r'(?m)(?:^|[;{}])\s*([A-Za-z_]\w*)\s*:(?!:)', rest))
    if any(target not in labels for target in re.findall(r'\bgoto\s+([A-Za-z_]\w*)', rest)):
        return True
    for found in re.finditer(r'\b(?:for|while|switch)\s*\(|\bdo\s*\{', rest):
        # a `break` inside an inner loop or switch is its own: blank that statement
        brace = rest.find('{', found.end() - 1)
        end = close(rest, brace) if brace >= 0 else -1
        if end >= 0:
            rest = rest[:brace] + ' ' * (end - brace + 1) + rest[end + 1:]
    return bool(re.search(r'\bbreak\b', rest))


def _indent(source, at):
    line = source[source.rfind('\n', 0, at) + 1:at]
    return line if not line.strip() else line[:len(line) - len(line.lstrip())]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    end = close(clean, part.opening)
    body = clean[part.opening:end]
    out = []
    for loop in _LOOP.finditer(clean, part.opening, end):
        opening = loop.end() - 1
        closing = close(clean, opening)
        head = _HEAD.match(clean, opening + 1)
        if closing < 0 or not head or not _VALUE.match(head['value']):
            continue
        target, paren = head['name'], head.end() - 1
        paren_end = close(clean, paren, '(', ')')
        leave = _EXIT.match(clean, paren_end + 1) if paren_end >= 0 else None
        if not leave or _EFFECT.search(clean[paren + 1:paren_end]):
            continue
        rest = clean[leave.end():closing]
        word = re.compile(rf'(?<![\w.>]){target}\b')
        if (word.search(clean[paren:paren_end]) or word.search(rest) or word.search(head['value'])
                or not _local(body, target) or _other_exit(rest)):
            continue
        after = closing + 1
        if leave['label']:
            label = re.compile(rf'\s*{leave["label"]}\s*:').match(clean, after)
            if not label or len(re.findall(rf'\bgoto\s+{leave["label"]}\b', body)) != 1:
                continue
            after = label.end()
        statement = source[head.start('name'):source.index(';', head.start('value')) + 1]
        line_start = source.rfind('\n', 0, head.start('name')) + 1
        stop = head.start('name') + len(statement)
        if not source[line_start:head.start('name')].strip() and source[stop:stop + 1] == '\n':
            removal = (line_start, stop + 1, '')
        else:
            removal = (head.start('name'), stop, '')
        added = (after, after, f'\n{_indent(source, loop.start())}{statement}')
        out.append((FAMILY, edit(source, [removal, added])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
