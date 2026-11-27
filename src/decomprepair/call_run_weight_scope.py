"""Weight a straight run of calls together with nested one-shot scopes.

GCC 2.x counts references at the loop depth in flow.c, even for a one-shot
scope that produces no loop instructions. On one MIPS KMC O1 function, fifteen
scopes around four consecutive diagnostic calls changed register allocation
and took a 355-instruction-difference score to an exact match. These scopes are
allocation scaffolding and must be disclosed if used. The judge decides whether
any proposed depth helps; no control flow or call is moved or duplicated.
"""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'call_run_weight_scope'
IDENT = r'[A-Za-z_]\w*'
DEPTHS = (1, 4, 8, 12, 15)
LIMIT = 30


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b__(?:LINE|COUNTER)__\b', source + '\n' + header):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')\b', source + '\n' + header))
    pairs = brace_pairs(part.clean, part.opening, part.end + 1 if part.clean[part.end:part.end + 1] == '}' else part.end)
    if not pairs:
        return []
    result = []
    for opening, closing in sorted(pairs.items()):
        spans = statements(part.clean, opening + 1, closing)
        runs = []
        run = []
        for start, end in spans:
            text = part.clean[start:end]
            hit = re.match(r'\s*(' + IDENT + r')\s*\(', text)
            stop = close(part.clean, start + hit.end() - 1) if hit else None
            if (hit and hit[1] not in macros | {'if', 'while', 'for', 'switch', 'sizeof', 'return'}
                    and stop and re.fullmatch(r'\s*;', part.clean[stop:end])
                    and not set(re.findall(IDENT, text)) & macros):
                if run and run[-1][2] != hit[1]:
                    runs.append(run)
                    run = []
                run.append((start, end, hit[1]))
            else:
                runs.append(run)
                run = []
        runs.append(run)
        for run in runs:
            if len(run) < 3 or len(run) > 8:
                continue
            start, end = run[0][0], run[-1][1]
            block = source[start:end]
            for depth in DEPTHS:
                result.append((FAMILY, edit(source, [(start, end, 'do { ' * depth + block + ' } while (0);' * depth)])))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',), 'order': 95}
