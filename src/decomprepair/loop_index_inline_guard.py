"""A masked loop index kept in a local, and the identical-arm guard around the body, written the way the target needs them.

A search (or m2c, for the first part) leaves a copy loop like

    IDX = C & 0xFF;                       /* before the loop */
    do { if (G) { C += 1; D[IDX] = S[IDX]; IDX = C & 0xFF; } else { <the same> } } while (S[C & 0xFF] != 0);

where the local `IDX` holds the masked counter across the increment. It is one pseudo set twice and used in both
halves of the body, so the allocator treats it as a global and gives it `$v1` while the loads take `$v0`, the other way
round from the target, which recomputes the mask at each use (`andi` four times, two registers). Inlining it needs the
increment moved after the stores (they read the old index), and the guard's condition is the other lever: the guard
keeps its condition's local alive through the loop (`if (var_v1)`: that float result stayed in a register for the whole
copy, and the third saved register went to the wrong value), while a global read that the identical arms make dead
leaves every register to the body. Measured on a 157-instruction sound-engine setup function with the app's judge,
from the saved best after `quotient_chain_stage`: 280 -> 235 (index inlined) -> 195 (guard on a global) and then
`reused_counter_split_scope` took 195 -> 35.

Three children: the index inlined, the guard's condition swapped for each global the function stores to (at most
three), and both. That the guard's condition is what extends the local's range is read from the registers, not from
the compiler's source: a hypothesis. The guard itself is scaffolding the match relies on (the arms are the same), kept
because the permuter has found it as a lever before (`identical_arm_collapse` writes it back out once the match is made).
"""
import re

from .csource import _blank, find

FAMILY_INLINE = 'loop_index_inline'
FAMILY_GUARD = 'identical_guard_global'
FAMILY_BOTH = 'loop_index_inline_guard'
FAMILIES = (FAMILY_INLINE, FAMILY_GUARD, FAMILY_BOTH)
ID = r'[A-Za-z_]\w*'
LIMIT_GLOBALS = 3
_DO = re.compile(r'\bdo\s*\{')
_IF = re.compile(rf'if\s*\(\s*(?P<cond>{ID})\s*\)\s*\{{')
_MASKED = re.compile(rf'(?P<idx>{ID})\s*=\s*\(?\s*(?P<counter>{ID})\s*&\s*(?P<mask>0[xX][0-9A-Fa-f]+|\d+)\s*\)?')


def _close(text, open_index):
    depth = 0
    for i in range(open_index, len(text)):
        depth += text[i] == '{'
        depth -= text[i] == '}'
        if not depth:
            return i
    return None


def _statements(text):
    """The simple statements of a brace-free run (`a = b; c += 1;`), or None when anything else is in it."""
    if re.search(r'[{}]|\b(?:if|else|do|while|for|switch|goto|return|break|continue)\b', text):
        return None
    parts = [p.strip() for p in text.split(';')]
    if parts[-1]:
        return None
    return [p for p in parts[:-1] if p]


def _arm_rewrite(statements):
    """(index, counter, mask, new statements) when the arm is `C += 1; <stores through IDX>; IDX = C & M;`."""
    if len(statements) < 3:
        return None
    inc = re.fullmatch(rf'(?P<c>{ID})\s*\+=\s*1|(?P<c2>{ID})\s*=\s*(?P=c2)\s*\+\s*1', statements[0])
    last = _MASKED.fullmatch(statements[-1])
    if not inc or not last:
        return None
    counter = inc['c'] or inc['c2']
    middle = statements[1:-1]
    index = last['idx']
    if last['counter'] != counter or index == counter:
        return None
    if not any(re.search(rf'\b{index}\b', s) for s in middle) or any(re.search(rf'\b{counter}\b', s) for s in middle):
        return None
    masked = f'{counter} & {last["mask"]}'
    rewritten = []
    for statement in middle:
        statement = re.sub(rf'\[\s*{index}\s*\]', f'[{masked}]', statement)
        rewritten.append(re.sub(rf'\b{index}\b', f'({masked})', statement))
    return index, counter, last['mask'], rewritten + [statements[0]]


def _globals(clean, span, header):
    """Scalar globals the function stores to, in order of first store (the guard reads one of them)."""
    scalars = set(re.findall(rf'extern\s+(?:volatile\s+)?(?:const\s+)?(?:s|u)(?:8|16|32)\s+({ID})\s*;', header + '\n' + clean))
    found = []
    for hit in re.finditer(rf'(?m)^\s*({ID})\s*=[^=]', clean[span[0]:span[1]]):
        if hit[1] in scalars and hit[1] not in found:
            found.append(hit[1])
    return found


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    for do in _DO.finditer(clean, *span):
        end = _close(clean, do.end() - 1)
        tail = re.match(r'\s*while\s*\(', clean[end + 1:]) if end else None
        if not tail:
            continue
        body = (do.end(), end)
        inner = clean[body[0]:body[1]]
        guard = _IF.match(inner.lstrip())
        arms = []
        if guard:
            first = inner.index('{')
            first_end = _close(inner, first)
            after = re.match(r'\s*else\s*\{', inner[first_end + 1:])
            if first_end is None or not after:
                continue
            second = first_end + 1 + after.end() - 1
            second_end = _close(inner, second)
            if second_end is None or inner[second_end + 1:].strip() or inner[:first].lstrip()[:2] != 'if':
                continue
            arms = [(body[0] + first + 1, body[0] + first_end), (body[0] + second + 1, body[0] + second_end)]
        else:
            arms = [body]
        rewrites = []
        for a, b in arms:
            statements = _statements(clean[a:b])
            rewrite = _arm_rewrite(statements) if statements else None
            if not rewrite:
                rewrites = []
                break
            rewrites.append(rewrite)
        if not rewrites or len({r[:3] for r in rewrites}) != 1:
            continue
        index, counter, mask, _ = rewrites[0]
        # the preheader assignment `IDX = C & M;` and no other use of the index anywhere else
        pre = re.search(rf'(?m)^[^\S\n]*{index}\s*=\s*\(?\s*{counter}\s*&\s*{re.escape(mask)}\s*\)?\s*;[^\S\n]*\n', clean[:do.start()])
        pre_all = [m for m in re.finditer(rf'\b{index}\b', clean[span[0]:span[1]])]
        declaration = re.search(rf'(?m)^[^\S\n]*(?:s|u)(?:8|16|32)\s+{index}\s*;[^\S\n]*\n', clean[span[0]:do.start()])
        expected = 1 + bool(declaration) + sum(len(re.findall(rf'\b{index}\b', clean[a:b])) for a, b in arms)
        if not pre or len(pre_all) != expected or pre.start() < span[0]:
            continue
        result = []
        indent = re.match(r'[^\S\n]*', source[source.rfind('\n', 0, arms[0][0]) + 1:]).group() + '  '
        pieces = []
        for (a, b), (_, _, _, statements) in zip(arms, rewrites):
            pieces.append((a, b, '\n' + '\n'.join(f'{indent}{s};' for s in statements) + '\n' + indent[:-2]))
        text = source
        for a, b, new in sorted(pieces, reverse=True):
            text = text[:a] + new + text[b:]
        text = text[:pre.start()] + text[pre.end():]
        if declaration:  # earlier in the text than the preheader, so its offsets are unchanged
            text = text[:span[0] + declaration.start()] + text[span[0] + declaration.end():]
        result.append((FAMILY_INLINE, text))
        if guard:
            cond = guard['cond']
            condition = re.compile(rf'(\bif\s*\(\s*){cond}(\s*\))')
            in_source = condition.search(source, body[0])
            in_inlined = condition.search(text, text.index('do', max(0, span[0])))
            for global_name in _globals(clean, span, header)[:LIMIT_GLOBALS]:
                if global_name == cond or not in_source or not in_inlined:
                    continue
                result.append((FAMILY_GUARD, source[:in_source.start()] + in_source[1] + global_name + in_source[2]
                               + source[in_source.end():]))
                result.append((FAMILY_BOTH, text[:in_inlined.start()] + in_inlined[1] + global_name + in_inlined[2]
                               + text[in_inlined.end():]))
        return result
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
