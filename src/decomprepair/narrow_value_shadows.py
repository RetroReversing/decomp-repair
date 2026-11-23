"""Narrow shadows of a loop's values: a 16-bit copy that is read where the code casts, a copy at the head of an arm, a
counter that is wide while its test narrows it.

Three edits that a rewritten display-list loop (KMC GCC 2.7.2, a 664-instruction sprite drawer) needed one after the other
(6035 -> 3175 with the first lines of the rewrite, then 3115 -> 2840 -> 2430 for these), each one a copy the target has
and a plain spelling folds away:

  narrow_cast_shadow   `ty = E; ... ((u16) ty) * 2 ... ((u16) ty + y) ...` -> `ty = E; __repair_ty_u16 = ty; ... __repair_ty_u16 * 2 ...`
                       A cast of a wide local is an `andi` at every use, and cse keeps one register for both. A
                       `u16` local is its own (HImode) pseudo: the target's `move $t5, $t0` after the value, the
                       extension at the uses and the original register free for the arm that rewrites it.
  arm_head_copy        `x = E; if (c) { ... x ... x ... }` -> `x = E; if (c) { __repair_x_arm = x; ... __repair_x_arm ... }`
                       The copy at the head of one arm (a delay-slot `move` in the target), so the arm reads its own
                       register and the other arm keeps the original. (Hypothesis: cse's equivalence classes end at the
                       branch, so the two arms are allocated apart.)
  counter_cast_test    `u16 i; for (i = 0; i < n; i++) { ... a * i ... }` -> `s32 i; for (i = 0; (u16) i < n; i++) ...`
                       The counter itself stays unextended (the target multiplies by it directly and only the test
                       narrows it), where a `u16` counter is extended before every use.

Children carry the family name; only integer locals are rewritten and the original statements are untouched except for the
read names. The candidate is never a verdict: the judge decides.
"""
import re

from .c_scan import close, enclosing_block
from .csource import _blank, find

FAMILY_CAST = 'narrow_cast_shadow'
FAMILY_ARM = 'arm_head_copy'
FAMILY_COUNTER = 'counter_cast_test'
FAMILIES = (FAMILY_CAST, FAMILY_ARM, FAMILY_COUNTER)
_ID = r'[A-Za-z_]\w*'
_WIDE = ('s32', 'u32', 'int', 'unsigned int', 'signed int', 'long', 'unsigned long')
_NARROW = ('u16', 's16', 'u8', 's8')
_MAX_CHILDREN = 24
_DECLARATION = re.compile(r'(?m)^([ \t]*)((?:unsigned |signed |const |register )*[A-Za-z_]\w*)[ \t]+([^;(){}\n]+);')
_CAST = re.compile(rf'\(\s*(u16|s16|u8|s8)\s*\)\s*({_ID})\b(?!\s*[\[(.]|->)')


def _declared(clean, lo, hi):
    """{name: type} of the plain integer locals declared in clean[lo:hi]."""
    out = {}
    for m in _DECLARATION.finditer(clean, lo, hi):
        kind = m.group(2).strip()
        if kind not in _WIDE and kind not in _NARROW:
            continue
        for part in m.group(3).split(','):
            ident = part.strip()
            if re.fullmatch(_ID, ident):
                out[ident] = kind
    return out


def _writes(text, name):
    """True when `text` assigns, steps or takes the address of `name`."""
    n = re.escape(name)
    return re.search(rf'(?<![\w.>]){n}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{n}\b|(?<![\w.>]){n}\s*(?:\+\+|--)|&\s*{n}\b', text) is not None


def _reads(text, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b(?!\s*\()', text)]


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    return (clean, opening, span[1]) if opening >= 0 else None


def _declare(source, opening, line):
    """`source` with the declaration `line` added as the first statement of the function body at `opening`."""
    return f'{source[:opening + 1]}\n  {line}{source[opening + 1:]}'


def _unique(clean, base):
    n = base
    while re.search(rf'\b{re.escape(n)}\b', clean):
        n += '_'
    return n


def _assign_before(clean, name, lo, hi):
    """(start, end) of the last statement `name = ...;` in clean[lo:hi] that has no other write to `name` after it."""
    last = None
    for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*=(?!=)[^;{{}}]*;', clean[lo:hi]):
        last = (lo + m.start(), lo + m.end())
    return last


def _cast_children(source, clean, opening, end):
    declared = _declared(clean, opening, end)
    groups = {}
    for m in _CAST.finditer(clean, opening, end):
        v = m.group(2)
        if declared.get(v) in _WIDE:
            groups.setdefault((m.group(1), v), []).append(m)
    out = []
    for (kind, v), hits in groups.items():
        if len(hits) < 2:
            continue
        first, last = hits[0].start(), hits[-1].end()
        # the value is set once in a block that holds every cast, and nothing writes it from there to the last cast
        found = _assign_before(clean, v, opening, first)
        if not found:
            continue
        block = enclosing_block(clean, found[0], opening)
        if block < 0 or close(clean, block) < last or _writes(clean[found[1]:last], v):
            continue
        shadow = _unique(clean, f'__repair_{v}_{kind}')
        edited = source
        for m in reversed(hits):
            edited = f'{edited[:m.start()]}{shadow}{edited[m.end():]}'
        edited = f'{edited[:found[1]]} {shadow} = {v};{edited[found[1]:]}'
        out.append((FAMILY_CAST, _declare(edited, opening, f'{kind} {shadow};')))
    return out


def _if_arms(clean, lo, hi):
    """(`if` start, [(open, close), ...]) for each braced `if` / `else` arm in clean[lo:hi]."""
    arms = []
    for m in re.finditer(r'\bif\s*\(', clean[lo:hi]):
        at = lo + m.start()
        depth, i = 0, lo + m.end() - 1
        while i < hi:
            depth += (clean[i] == '(') - (clean[i] == ')')
            i += 1
            if depth == 0:
                break
        rest = re.match(r'\s*\{', clean[i:hi])
        if not rest:
            continue
        opening = i + rest.end() - 1
        tail = close(clean, opening)
        if tail < 0:
            continue
        found = [(opening, tail)]
        other = re.match(r'\s*else\s*\{', clean[tail + 1:hi])
        if other:
            second = tail + 1 + other.end() - 1
            end = close(clean, second)
            if end > 0:
                found.append((second, end))
        arms.append((at, found))
    return arms


def _arm_children(source, clean, opening, end):
    declared = _declared(clean, opening, end)
    out = []
    for at, arms in _if_arms(clean, opening, end):
        parent = enclosing_block(clean, at, opening)
        if parent < 0:
            continue
        for start, stop in arms:
            body = clean[start + 1:stop]
            for v, kind in declared.items():
                if kind not in _WIDE or len(_reads(body, v)) < 2 or _writes(body, v):
                    continue
                if not _assign_before(clean, v, parent, at):
                    continue
                shadow = _unique(clean, f'__repair_{v}_arm')
                inner = re.sub(rf'(?<![\w.>]){re.escape(v)}\b(?!\s*\()', shadow, source[start + 1:stop])
                edited = f'{source[:start + 1]}\n{shadow} = {v};{inner}{source[stop:]}'
                out.append((FAMILY_ARM, _declare(edited, opening, f'{kind} {shadow};')))
    return out


_FOR = re.compile(rf'\bfor\s*\(\s*(?P<v>{_ID})\s*=\s*[^;]+;\s*(?P<test>(?P=v)\s*<)\s*(?P<limit>[^;]+);\s*(?:(?P=v)\s*\+\+|\+\+\s*(?P=v)|(?P=v)\s*\+=\s*1)\s*\)')


def _counter_children(source, clean, opening, end):
    """One child per narrow counter of a `for (v = a; v < n; v++)` loop, and one with every such counter."""
    narrow = {}
    for m in _DECLARATION.finditer(clean, opening, end):
        if m.group(2).strip() in ('u16', 's16'):
            for part in m.group(3).split(','):
                if re.fullmatch(_ID, part.strip()):
                    narrow[part.strip()] = m
    loops = {}
    for m in _FOR.finditer(clean, opening, end):
        if m.group('v') in narrow and not re.match(r'\(?\s*(?:u16|s16)\b', m.group('limit')):
            loops.setdefault(m.group('v'), m)
    picks = [[v] for v in loops] + ([list(loops)] if len(loops) > 1 else [])
    out = []
    for names in picks:
        edited = source
        for v in sorted(names, key=lambda n: -loops[n].start('test')):
            kind = narrow[v].group(2).strip()
            a, b = loops[v].span('test')
            edited = f'{edited[:a]}({kind}) {v} <{edited[b:]}'
        # the declarations come before every loop, so their offsets are unchanged
        declarations = {}
        for v in names:
            declarations[narrow[v].start()] = narrow[v]
        for m in sorted(declarations.values(), key=lambda d: -d.start()):
            parts = [p.strip() for p in m.group(3).split(',')]
            wide = [p for p in parts if p in names]
            keep = [p for p in parts if p not in names]
            lines = ([f'{m.group(1)}{m.group(2).strip()} {", ".join(keep)};'] if keep else []) + [f'{m.group(1)}s32 {", ".join(wide)};']
            edited = f'{edited[:m.start()]}{chr(10).join(lines)}{edited[m.end():]}'
        out.append((FAMILY_COUNTER, edited))
    return out


def variants(source, name):
    found = _body(source, name)
    if not found:
        return []
    clean, opening, end = found
    out = []
    for build in (_cast_children, _arm_children, _counter_children):
        out.extend(build(source, clean, opening, end))
    return out[:_MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
