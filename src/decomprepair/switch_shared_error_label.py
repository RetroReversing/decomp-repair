"""Move a shared error tail into the switch case that jumps to it.

One MIPS KMC O1 state machine used a label in the non-switch arm for a
constant error store and counter increment. The other arm's switch jumped
back into that label. Keeping the early-return path in place and moving the
shared tail into its switch case improved the judge from 1195 to 655. Gotos
still execute the same store and increment, and a break leaves the switch.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close
from .run_weight_scope import _statement_end

FAMILY = 'switch_shared_error_label'
LIMIT = 8


def variants(source, name, header=''):
    part = view(source, name)
    context = source + '\n' + header
    if not part or re.search(r'\b__(?:LINE|COUNTER)__\b', context):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')\b', context))
    clean = part.clean
    result = []
    for label in re.finditer(rf'(?m)^\s*({IDENT})\s*:(?!:)', part.body):
        tag = label[1]
        if tag in macros or tag in {'case', 'default'}:
            continue
        start = part.opening + 1 + label.start(1)
        store_start = part.opening + 1 + label.end()
        store_end = _statement_end(clean, store_start, part.end)
        if store_end < 0:
            continue
        store = clean[store_start:store_end]
        # Only a constant indexed store, possibly within one-shot wrappers.
        if not re.fullmatch(rf'\s*(?:do\s*\{{\s*)*{IDENT}\s*\[\s*{IDENT}\s*\]\s*=\s*{NUMBER}\s*;\s*(?:\}}\s*while\s*\(\s*0\s*\)\s*;\s*)*', store):
            continue
        if store.count('{') != store.count('}') or set(re.findall(IDENT, store)) & macros:
            continue
        inc = re.match(rf'\s*({IDENT})\s*\+\+\s*;', clean[store_end:part.end])
        if not inc or inc[1] in macros:
            continue
        tail_end = store_end + inc.end()
        arm = re.match(r'\s*}\s*else\s*{\s*switch\s*\(', clean[tail_end:part.end])
        if not arm:
            continue
        paren = tail_end + arm.end() - 1
        after = close(clean, paren)
        switch_head = re.match(r'\s*{', clean[after:part.end]) if after else None
        if not switch_head:
            continue
        opening = after + switch_head.end() - 1
        switch_end = close(clean, opening, '{', '}')
        if not switch_end or not re.match(r'\s*}', clean[switch_end:part.end]):
            continue
        body = clean[opening + 1:switch_end - 1]
        if re.search(rf'(?:^|[;{{}}:])\s*(?!(?:goto|return|break|continue|case|default)\b)(?:(?:const|volatile|static|register|unsigned|signed)\s+)*{IDENT}\s+\*?\s*{IDENT}\s*(?:[;=,\[])', body):
            continue  # moving into a nested scope must not bind to a shadow
        if len(re.findall(rf'\bgoto\s+{re.escape(tag)}\s*;', part.body)) != 1:
            continue
        case = re.search(rf'\bcase\s+{NUMBER}\s*:\s*(?:do\s*{{\s*)?goto\s+{re.escape(tag)}\s*;\s*(?:}}\s*while\s*\(\s*0\s*\)\s*;)?', body)
        if not case:
            continue
        # The matched case must be at the switch's own brace level.
        prefix = body[:case.start()]
        if prefix.count('{') != prefix.count('}'):
            continue
        case_start = opening + 1 + case.start()
        case_end = opening + 1 + case.end()
        case_head = re.match(rf'\bcase\s+{NUMBER}\s*:', clean[case_start:case_end]).group()
        tail = source[start:tail_end].strip()
        moved = case_head + '\n' + tail + '\n break;'
        result.append((FAMILY, edit(source, [(start, tail_end, f'goto {tag};'), (case_start, case_end, moved)])))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
