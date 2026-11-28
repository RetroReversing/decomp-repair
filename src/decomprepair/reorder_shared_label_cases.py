"""Move one non-fallthrough switch case while retaining shared internal labels.

A MIPS KMC O2 MIDI dispatcher had seven cases, one jumping into a labeled
block in another. Moving the pressure case before the controller case kept
the shared jump and improved one linked judge from 9066 to 6551. Only braced
case bodies ending in break, or a bare goto, are reordered; incoming jumps
from outside the switch and fallthrough cases are rejected.
"""
import re

from .arm_block_support import brace_pairs
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close
from .switch_case_order_repairs import LABEL

FAMILY = 'reorder_shared_label_cases'
LIMIT = 56


def variants(source, name, header=''):
    part = view(source, name)
    context = source + '\n' + header
    if not part or re.search(r'\b__(?:LINE|COUNTER)__\b', context):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')\b', context))
    clean = part.clean
    result = []
    for head in re.finditer(r'\bswitch\s*\(', clean[part.opening:part.end]):
        paren = part.opening + head.end() - 1
        after = close(clean, paren)
        brace = re.match(r'\s*{', clean[after:part.end]) if after else None
        if not brace:
            continue
        opening = after + brace.end() - 1
        end = close(clean, opening, '{', '}')
        pairs = brace_pairs(clean, opening, end) if end else None
        if not pairs:
            continue
        labels = [m for m in LABEL.finditer(clean, opening + 1, end - 1)
                  if not any(a != opening and a < m.start() < b for a, b in pairs.items())]
        if not 3 <= len(labels) <= 9 or labels[-1]['value'] is not None or any(m['value'] is None for m in labels[:-1]):
            continue
        spans = []
        for i, label in enumerate(labels[:-1]):
            stop = labels[i + 1].start()
            body = clean[label.end():stop].strip()
            if re.fullmatch(r'goto\s+' + IDENT + r'\s*;', body):
                spans.append((label.start(), stop))
                continue
            if not body.startswith('{'):
                break
            block = close(body, 0, '{', '}')
            if not block or not re.fullmatch(r'\s*break\s*;\s*', body[block:]):
                break
            spans.append((label.start(), stop))
        if len(spans) != len(labels) - 1:
            continue
        internal = clean[opening:end]
        named = set(re.findall(r'(?<![\w?:])(' + IDENT + r')\s*:(?!:)', internal)) - {'case', 'default'}
        jumps = set(re.findall(r'\bgoto\s+(' + IDENT + r')\s*;', internal))
        if not named & jumps or named & macros:
            continue
        outside = clean[part.opening:opening] + clean[end:part.end]
        if any(re.search(r'\bgoto\s+' + re.escape(label) + r'\b', outside) for label in named):
            continue
        # Reconstructing a case must not expand a macro that can add labels or jumps.
        null_defs = re.findall(r'(?m)^\s*#\s*define\s+NULL\s+([^\n]+)', context)
        safe_null = (null_defs and not re.search(r'(?m)^\s*#\s*undef\s+NULL\b', context)
                     and all(re.fullmatch(r'\s*\(\s*\(\s*void\s*\*\s*\)\s*0\s*\)\s*', d) for d in null_defs))
        unsafe_macros = macros - ({'NULL'} if safe_null else set())
        if unsafe_macros & set(re.findall(IDENT, internal)):
            continue
        texts = [source[a:b] for a, b in spans]
        for old in range(len(texts)):
            for new in range(len(texts)):
                if old == new:
                    continue
                order = list(range(len(texts)))
                item = order.pop(old)
                order.insert(new, item)
                changed = ''.join(texts[i] for i in order)
                result.append((FAMILY, edit(source, [(spans[0][0], spans[-1][1], changed)])))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
