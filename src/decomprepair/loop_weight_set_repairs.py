"""Every step and start of the loop locals wrapped in a one-shot scope at once, so their allocation order moves together.

GCC 2.x hands the saved registers to pseudos in order of floor_log2(refs) * refs / live length, and counts a reference
once per loop it sits in (`allocation_priority.py` in the app reads the table back). `do { x += 8; } while (0);` is one
loop more round the statement, at no instruction or run-time cost, so it raises that one reference's weight. A
function whose saved registers are all in the wrong order needs several such weights at once; `loop_weight_scope`
offers one statement per child, and every one of those children alone leaves the score where it was or worse (a plateau
the greedy chain cannot cross).

A 84-instruction KMC N64 initialiser (two `goto` loops over the same record, `-G0 -mips3 -mgp32 -mfp32 -O2`, saved
registers `$s2`..`$s5` in the wrong order, 30 -> 0 in the isolated judge) matched with every start (`x = 0;`) and every
step (`x += k;`, and the copy-then-step pair `t = x; x += 1;` of a call argument) wrapped once, and the step of the
induction pointer wrapped three times (`do { do { do { p += 8; } while (0); } while (0); } while (0);`). Of the sixty
combinations of depths the greedy lane could reach one statement at a time, none moved; this one is a single child.
Which pseudo wants the extra weight is read from the priority table; offered here without a compile, so each local's
steps take the deepest wrapper in turn. The saved best of that function also carried a union that shares one register
between two phases and a counter reused by the second loop; `variants` offers the union split (`phase_storage_split`)
and the counter split (`reused_temp_split`) first, as one child, because the weights only reach the target's order once
the second loop's pseudos are their own (alone each is worse: 30 -> 110 -> 135). The compiler's reasons are
hypotheses from the `-dl -dg` tables, not confirmed in its source. A candidate for the exact judge, never a verdict.
"""
import re

from . import phase_storage_split_repairs, reused_temp_split_repairs
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'loop_weight_set'
FAMILIES = (FAMILY,)
LIMIT = 16
MARK = '/*__repair_loop_weight*/'
_STEP = (rf'(?P<v>{IDENT})\s*(?:\+\+|--|[-+]=\s*(?:{IDENT}|{NUMBER})|=\s*(?P=v)\s*[-+]\s*(?:{IDENT}|{NUMBER}))\s*;')
_START = re.compile(rf'(?<=[;{{}}])(?P<lead>\s*)(?P<v>{IDENT})\s*=\s*{NUMBER}\s*;')
_STEPS = re.compile(rf'(?<=[;{{}}])(?P<lead>\s*)(?:(?P<copy>{IDENT})\s*=\s*(?P<src>{IDENT})\s*;\s*)?{_STEP}')
_PRE = re.compile(rf'(?<=[;{{}}])(?P<lead>\s*)(?:\+\+|--)\s*(?P<v>{IDENT})\s*;')


def _wrap(text, depth):
    return '{0}{1} {2}'.format('do { ' * depth, ' '.join(text.split()), '} while (0); ' * depth).rstrip()


def sites(source, name):
    """[(variable, kind, start, end)] of the starts and steps of the function's declared locals, in source order."""
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|setjmp)\b', part.body) or MARK in source:
        return []
    clean = part.clean
    declared = {m['n'] for m in re.finditer(
        rf'(?<=[;{{}}])\s*(?:unsigned\s+|signed\s+|const\s+)*(?:{IDENT})\s*\**\s*(?P<n>{IDENT})\s*(?:;|=)',
        clean[part.opening + 1:part.opening + 1 + _declarations_end(clean, part)])}
    found = []
    for m in _STEPS.finditer(clean, part.opening, part.end - 1):
        if m['v'] in declared and (not m['copy'] or (m['src'] == m['v'] and m['copy'] in declared)):
            found.append((m['v'], 'step', m.start() + len(m['lead']), m.end()))
    for m in _START.finditer(clean, part.opening, part.end - 1):
        if m['v'] in declared:
            found.append((m['v'], 'start', m.start() + len(m['lead']), m.end()))
    stepped = {v for v, kind, _, _ in found if kind == 'step'}
    found = [site for site in found if site[0] in stepped]
    # a start inside a step's span (`t = 0; t += 1;` cannot match both) is never wrapped twice
    found.sort(key=lambda s: s[2])
    return [site for i, site in enumerate(found) if not (i and site[2] < found[i - 1][3])]


def _declarations_end(clean, part):
    """Characters of the body that hold its leading declarations (up to the first statement that is not one)."""
    body = clean[part.opening + 1:part.end]
    end = 0
    for line in re.finditer(r'[^;{}]*[;{}]', body):
        text = line.group(0).strip()
        if re.match(rf'(?:unsigned\s+|signed\s+|const\s+)*(?:{IDENT})\s*\**\s*{IDENT}\s*;$', text) or text == '{' \
                or re.match(r'union\s*\w*\s*{', text) or text in ('}', ';') or re.match(r'(?:\w+\s+)+\w+;$', text):
            end = line.end()
            continue
        if re.match(rf'(?:{IDENT}\s+)+\**\s*{IDENT}\s*;', text):
            end = line.end()
            continue
        break
    return end


def _build(source, found, deep=None, depth=1):
    changes = []
    for variable, kind, start, end in found:
        text = _wrap(source[start:end], 3 if variable == deep else depth)
        changes.append((start, end, text if changes else MARK + text))
    return edit(source, changes)


def variants(source, name, header=''):
    """Each start and step wrapped once; twice; once with one local's steps wrapped three times. Plus the same after
    the union split and the reused-counter split when the saved source carries them."""
    out = []
    bases = [source]
    for family, text in phase_storage_split_repairs.variants(source, name):
        if family == phase_storage_split_repairs.FAMILY:
            bases = [text] + bases
            break
    split = []
    for base in bases[:1]:
        for family, text in reused_temp_split_repairs.variants(base, name):
            if family == reused_temp_split_repairs.FAMILY:
                split.append(text)
    for base in dict.fromkeys(split + bases):
        found = sites(base, name)
        if len({s[0] for s in found}) < 2 or len(found) < 3:
            continue
        # the second phase: from the first start of a local that an earlier step already advanced (the second loop's
        # preheader), through the end. The first loop's own starts and steps keep their weights.
        stepped, late = set(), None
        for index, (variable, kind, _, _) in enumerate(found):
            if kind == 'start' and variable in stepped:
                late = index
                break
            if kind == 'step':
                stepped.add(variable)
        parts = [found]
        if late:
            # ... and the earlier steps of the locals that run on into it (the counter shared by both loops)
            shared = {v for v, _, _, _ in found[late:]}
            parts.insert(0, [site for i, site in enumerate(found) if i >= late or (site[1] == 'step' and site[0] in shared)])
            parts.insert(1, found[late:])
        for part in parts:
            steppers = list(dict.fromkeys(v for v, kind, _, _ in part if kind == 'step'))
            for deep in [None] + steppers[::-1]:
                out.append((FAMILY, _build(base, part, deep, 1)))
            out.append((FAMILY, _build(base, part, None, 2)))
    return list(dict.fromkeys(out))[:LIMIT]
