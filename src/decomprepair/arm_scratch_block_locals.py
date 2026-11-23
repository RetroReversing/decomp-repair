"""A scratch local shared by the arms of a switch, given a block of its own in every arm that sets it before reading it (GCC 2.7.2, KMC, N64).

`u8 x, y, z;` declared once at the top and assigned in the arms (`x = q[i * 3]; y = q[i * 3 + 1]; z = q[i * 3 + 2];` inside
each arm's loop) is one pseudo register per name for the whole function: every arm's reference counts toward one
priority, so it is allocated early by global.c and gets a register of the group the other arms' values then miss, and the
arm that wants the target's `$v0/$v1/$t0` for them gets the next three. The game declared them in each arm (or the arm had
its own), where each is a short block-local quantity that local-alloc hands out in order. `local_web_split` does this for
a plain `name = expr;` at the arm's own level; here the first write is nested (in the body of the loop the arm runs) and
the arm's goto into a shared tail (`goto add_one;`) must stay outside the new braces.

`variants` takes a function with a `switch` and offers (`arm_scratch_block_locals`) the one child in which every arm
that sets such a scalar before reading it (the first reference of the name in the arm's statements is a plain assignment
that is unconditional in its block, and every other reference in the arm is in that block, after it) is wrapped from its
start to just before its closing `goto`/`break`/`return` in `{ T name; ... }`. A name is split only when every reference
to it in the function is in such an arm (an arm that declares its own `name` in a nested block keeps that one) and its
address is never taken. 805 from 950 on a 559-instruction N64 display-list builder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32
-mfp32 -O2`: two arms of four). The exact judge decides.
"""
import re

from .csource import find
from .pattern_repairs import close

FAMILY = 'arm_scratch_block_locals'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 12

_ID = r'[A-Za-z_]\w*'
_SCALAR = r'(?:[su](?:8|16|32)|unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|char|short|int)'
_DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{_SCALAR})[ \t]+(?P<name>{_ID})[ \t]*;[ \t]*\n')
_SWITCH = re.compile(r'\bswitch\s*\(')
_LABEL = re.compile(rf'(?m)^[ \t]*(?:case\b[^:\n]*|default)[ \t]*:|(?<![\w:?])\b(?!case\b|default\b){_ID}[ \t]*:(?![:=])')
_EXIT = re.compile(r'\b(?:goto\s+\w+|break|return\b[^;]*|continue)\s*;')


def _arms(clean, start, end):
    """(label_end, arm_end) for each arm of the switch body clean[start:end], split at its top-level case labels."""
    labels, depth = [], 0
    for hit in re.finditer(r'[{}]|\b(?:case\b[^:;{}]*|default)\s*:(?!:)', clean[start:end]):
        if hit[0] == '{':
            depth += 1
        elif hit[0] == '}':
            depth -= 1
        elif depth == 0:
            labels.append((start + hit.start(), start + hit.end()))
    arms = []
    for k, (_, label_end) in enumerate(labels):
        stop = labels[k + 1][0] if k + 1 < len(labels) else end
        if re.fullmatch(r'\s*', clean[label_end:stop]):
            continue  # a label that falls into the next one
        arms.append((label_end, stop))
    return arms


def _prefix(clean, start, stop):
    """The end of the arm's wrappable prefix: just before its first top-level `goto`/`break`/`return`/label, or its end."""
    depth = 0
    for hit in re.finditer(r'[{}]|\b(?:goto\s+\w+|break|return\b[^;]*|continue)\s*;|(?<![\w:?])[A-Za-z_]\w*[ \t]*:(?![:=])', clean[start:stop]):
        if hit[0] == '{':
            depth += 1
        elif hit[0] == '}':
            depth -= 1
        elif depth == 0:
            return start + hit.start()
    return stop


def _enclosing(clean, pos):
    """(start, end) of the innermost braces around `pos`, end None when they do not close."""
    depth = 0
    for at in range(pos - 1, -1, -1):
        if clean[at] == '}':
            depth += 1
        elif clean[at] == '{':
            if depth == 0:
                return at, close(clean, at, '{', '}')
            depth -= 1
    return 0, None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    clean = re.sub(r'(?s)/\*.*?\*/', lambda m: ' ' * len(m[0]), text)
    switch = _SWITCH.search(clean)
    if not switch:
        return []
    paren = close(clean, switch.end() - 1)
    brace = clean.find('{', paren)
    if not paren or brace < 0:
        return []
    shut = close(clean, brace, '{', '}')
    if not shut:
        return []
    arms = _arms(clean, brace + 1, shut - 1)
    if len(arms) < 2:
        return []
    wraps = [(s, _prefix(clean, s, e)) for s, e in arms]
    candidates = {}
    for decl in _DECL.finditer(clean):
        if decl.start() < brace and clean.count('{', 0, decl.start()) - clean.count('}', 0, decl.start()) == 1:
            candidates[decl['name']] = decl
    plans = {}
    for var, decl in candidates.items():
        if re.search(rf'&\s*{re.escape(var)}\b', clean):
            continue
        scopes = [_enclosing(clean, m.start()) for m in re.finditer(rf'\b{_SCALAR}\s+{re.escape(var)}\s*;', clean)
                  if m.start() != decl.start('type')]
        refs = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', clean)
                if not decl.start() <= m.start() < decl.end()
                and not any(a <= m.start() < b for a, b in scopes if b)]
        inside, outside = [], {}
        ok = True
        for pos in refs:
            arm = next((i for i, (s, e) in enumerate(wraps) if s <= pos < e), None)
            if arm is not None:
                inside.append((arm, pos))
                continue
            whole = next((i for i, (s, e) in enumerate(arms) if s <= pos < e), None)
            if whole is None:
                ok = False
                break
            outside.setdefault(whole, []).append(pos)
        # a reference left outside the wrapped part (a shared tail, a label) must itself set the name before reading it
        if ok and any(not re.match(rf'{re.escape(var)}\s*=(?!=)', clean[min(places):]) for places in outside.values()):
            ok = False
        if not ok or not inside:
            continue
        per_arm = {}
        for arm, pos in inside:
            per_arm.setdefault(arm, []).append(pos)
        good = {}
        for arm, positions in per_arm.items():
            s, e = wraps[arm]
            if any(s <= a < e for a, b in scopes if b):
                continue  # the arm has a name of its own
            first = positions[0]
            assign = re.match(rf'{re.escape(var)}\s*=(?!=)', clean[first:])
            if not assign:
                break
            depth_at = clean.count('{', s, first) - clean.count('}', s, first)
            block_start = max([m.end() for m in re.finditer(r'\{', clean[s:first]) if clean.count('{', s + m.end(), first) == clean.count('}', s + m.end(), first)] + [0]) + s
            block_end = close(clean, block_start - 1, '{', '}') if block_start > s else e
            if depth_at and not block_end:
                break
            if any(not block_start <= p < block_end for p in positions):
                break
            before = clean[block_start:first]
            if re.search(r'\b(?:if|else|while|for|switch)\b[^;{}]*$', before) or re.search(r'\bif\s*\([^;{}]*\)\s*$', before):
                break
            good[arm] = decl
        else:
            if good:
                plans[var] = (decl, good, bool(outside))
    if not plans:
        return []
    groups = {}
    for var, (decl, good, outside) in plans.items():
        groups.setdefault(tuple(sorted(good)), []).append(var)
    out = []
    # the names that go together (the same arms) as one child, every name of every arm as one, and each arm of a group alone
    # (the arms' edits are in different places, so a chain composes the ones that help)
    wanted = [(chosen, None) for chosen in list(groups.values()) + ([list(plans)] if len(groups) > 1 else [])]
    wanted += [(chosen, arm) for chosen in groups.values() for arm in sorted(plans[chosen[0]][1]) if len(plans[chosen[0]][1]) > 1]
    for chosen, only_arm in wanted[:MAX_CHILDREN]:
        inserts, removals = {}, []
        for var in chosen:
            decl, good, outside = plans[var]
            for arm in good:
                if only_arm is None or arm == only_arm:
                    inserts.setdefault(arm, []).append(decl)
            if not outside and only_arm is None:
                removals.append(decl)
        edits = []
        for arm, decls in inserts.items():
            s, e = wraps[arm]
            indent = re.match(r'\s*', clean[s:e])[0]
            names = ''.join(f'{indent}{d["type"]} {d["name"]};' for d in sorted(decls, key=lambda d: d.start()))
            edits.append((e, e, '\n' + indent.lstrip('\n') + '}'))
            edits.append((s, s, ' {' + names))
        for decl in removals:
            edits.append((decl.start(), decl.end(), ''))
        child = text
        for start, end, replacement in sorted(edits, reverse=True):
            child = child[:start] + replacement + child[end:]
        out.append((FAMILY, source[:span[0]] + child + source[span[1]:]))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
