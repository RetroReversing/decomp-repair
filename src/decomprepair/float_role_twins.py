"""One float constant local split into a twin per call-argument role (a viewport helper, 14156 -> 4500).

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`, O32: a float argument travels in `$a1`..`$a3` or on the stack). Matched
on a split-screen setup routine that calls one rectangle helper (`obj, x, y, w, h, ox, oy`) from a dozen places with
the screen's half sizes `160.0f` and `120.0f`. The target kept each half size in TWO saved registers at once, one
float (`mtc1 $at, $f26`) and one integer (`lui $fp, 0x42f0`, the other copied from it with `mfc1 $s6, $f26` or
`mtc1 $fp, $f30`), and read the integer one where an argument goes to `$a1`..`$a3` (`move $a2, $fp`) and the float one
where a sum or a stack argument needs it (`add.s $f0, $f30, $f30`, `swc1 $f30, 0x10($sp)`). One local per constant
(`f32 centerX = 160.0f;`) is one pseudo, and the allocator gives it one register: 21 differing prologue and argument
rows, every saved register shifted by one, 14156. Four locals, each used for one argument slot of the helper, gave the
target's prologue at once and 4500 with the rest unchanged (302 differing rows -> 116).

float_twin_toggle
    Where two or more such locals hold the same literal (the twins above, or ones written that way), one read of one
    twin is renamed to a sibling, one child per read and sibling: which twin each read names decides which pseudo
    the allocator sees it in (the first expression of a basic block is canonicalised by cse, a later block keeps the
    name). A greedy chain over these toggles moved the 16436 children of `float_role_twins` to 5155 on the function
    above (the hand-made choice was 4500).

float_role_twins
    An `f32 name = <literal>;` local that is never assigned again, whose address is never taken and that is read in
    arguments of calls at two or more different argument positions of the same callee gets one twin per position
    (`name_r1 = <literal>;`, `name_r3 = <literal>;`), and each read inside that position's argument (a sum or a
    product in it too) names its twin. Reads outside any call's arguments (`half = name * 0.5f;`) go to the twin of the
    lowest position (child `low`) or the highest (`high`), the original declaration is dropped, and the twins are
    declared in position order across all the split locals, which is the order the target loads them. Every eligible
    local is split in one child (they only pay off together: the pseudos compete for the same few saved registers); a
    child per single local follows.

Hypothesis from the match, not from the compiler source: pseudos with different reference counts and live ranges are
ranked apart by global.c (`floor_log2 (refs) * refs / live`), and regclass prefers the integer class for a pseudo that
mostly feeds argument moves. The exact judge decides every child.
"""
import re

from .integer_repair_support import IDENT, split_args, view
from .pattern_repairs import close

FAMILY = 'float_role_twins'
TOGGLE = 'float_twin_toggle'
FAMILIES = (FAMILY, TOGGLE)
LIMIT = 6
TOGGLE_LIMIT = 64
_FLOAT = r'(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?[fF]?'
_DECL = re.compile(rf'(?P<line>^[ \t]*)(?P<type>f32|float)[ \t]+(?P<name>{IDENT})[ \t]*=[ \t]*(?P<value>{_FLOAT})[ \t]*;[ \t]*\n',
                   re.M)
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'else', 'do', 'case'}
_TYPES = {'f32', 'f64', 'float', 'double', 's8', 'u8', 's16', 'u16', 's32', 'u32', 's64', 'u64', 'int', 'char', 'short',
          'long', 'unsigned', 'signed', 'void', 'const', 'volatile', 'struct'}


def _enclosing_call(clean, at, low):
    """(callee, argument index, start, end) of the innermost call whose argument list holds `at`, or None."""
    depth = 0
    pos = at
    while pos > low:
        pos -= 1
        char = clean[pos]
        if char in ')]}':
            depth += 1
        elif char in '([{':
            if depth:
                depth -= 1
                continue
            if char != '(':
                return None
            head = re.search(rf'({IDENT})\s*$', clean[low:pos])
            if head and head[1] not in _KEYWORDS and head[1] not in _TYPES:
                end = close(clean, pos)
                if not end:
                    return None
                args = split_args(clean[pos + 1:end - 1])
                for index, (start, stop) in enumerate(args):
                    if pos + 1 + start <= at < pos + 1 + stop:
                        return head[1], index, pos + 1 + start, pos + 1 + stop
                return None
            # a cast, a group or a keyword's parentheses: keep looking outward
        elif char == ';':
            return None
    return None


def _reads(clean, name, low, high, declared):
    found = []
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[low:high]):
        start = low + hit.start()
        if declared[0] <= start < declared[1]:
            continue
        found.append((start, low + hit.end()))
    return found


def _candidates(part):
    """[(name, type, literal, declaration span, [(start, end, key or None)])] for the splittable locals."""
    clean = part.clean
    low, high = part.opening + 1, part.end - 1
    result = []
    for decl in _DECL.finditer(clean, low, high):
        name = decl['name']
        prefix = clean[low:decl.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        body = clean[low:high]
        if len(re.findall(rf'\b(?:f32|float|f64|double|{IDENT})\s*\**\s*{re.escape(name)}\s*[;=,\[]', body)) != 1:
            continue
        if re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b'
                     rf'|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b', clean[decl.end():high]):
            continue
        uses = []
        for start, end in _reads(clean, name, decl.end(), high, (decl.start(), decl.end())):
            call = _enclosing_call(clean, start, low)
            uses.append((start, end, (call[0], call[1]) if call else None))
        keys = {key for _, _, key in uses if key}
        by_callee = {}
        for callee, index in keys:
            by_callee.setdefault(callee, set()).add(index)
        if not any(len(indexes) >= 2 for indexes in by_callee.values()):
            continue
        result.append((name, decl['type'], decl['value'], (decl.start(), decl.end()), uses, decl['line']))
    return result


def _split(source, chosen, rest):
    """Rewrite `chosen` (candidates) together; reads outside calls go to the `rest` ('low' or 'high') position's twin."""
    edits = []
    declarations = []
    for name, kind, value, span, uses, indent in chosen:
        by_callee = {}
        for _, _, key in uses:
            if key:
                by_callee.setdefault(key[0], set()).add(key[1])
        callee = max(by_callee, key=lambda c: (len(by_callee[c]), -list(by_callee).index(c)))
        indexes = sorted(by_callee[callee])
        names = {index: f'{name}_r{index}' for index in indexes}
        anchor = min(indexes) if rest == 'low' else max(indexes)
        for start, end, key in uses:
            if key and key[0] == callee:
                edits.append((start, end, names[key[1]]))
            elif key is None or key[0] != callee:
                edits.append((start, end, names[anchor]))
        for index in indexes:
            declarations.append((index, name, f'{indent}{kind} {names[index]} = {value};\n'))
        edits.append((span[0], span[1], ''))
    first = min(item[3][0] for item in chosen)
    text = ''.join(line for _, _, line in sorted(declarations, key=lambda item: (item[0], item[1])))
    edits.append((first, first, text))
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def _twin_groups(part):
    """{literal: [names]} of never-assigned float locals that share one literal initialiser (two or more each)."""
    clean = part.clean
    low, high = part.opening + 1, part.end - 1
    groups = {}
    for decl in _DECL.finditer(clean, low, high):
        name = decl['name']
        prefix = clean[low:decl.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        if len(re.findall(rf'\b(?:f32|float|f64|double|{IDENT})\s*\**\s*{re.escape(name)}\s*[;=,\[]', clean[low:high])) != 1:
            continue
        if re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b'
                     rf'|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b', clean[decl.end():high]):
            continue
        groups.setdefault(decl['value'], []).append((name, decl.start(), decl.end()))
    return {value: names for value, names in groups.items() if len(names) >= 2}


def _toggles(source, part):
    groups = _twin_groups(part)
    found = []
    for names in groups.values():
        for name, start, end in names:
            for use_start, use_end in _reads(part.clean, name, end, part.end - 1, (start, end)):
                for other, _, _ in names:
                    if other != name:
                        found.append((use_start, use_end, other))
    found.sort()
    if len(found) > TOGGLE_LIMIT:
        step = len(found) / TOGGLE_LIMIT
        found = [found[int(i * step)] for i in range(TOGGLE_LIMIT)]
    return [(TOGGLE, source[:start] + other + source[end:]) for start, end, other in found]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    found = _candidates(part)
    toggles = _toggles(source, part)
    if not found:
        return toggles
    result = []
    for rest in ('low', 'high'):
        result.append((FAMILY, _split(source, found, rest)))
    if len(found) > 1:
        for one in found:
            result.append((FAMILY, _split(source, [one], 'low')))
    unique = []
    for family, text in result:
        if text != source and all(text != other for _, other in unique):
            unique.append((family, text))
    return unique[:LIMIT] + toggles


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
