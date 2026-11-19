"""A store m2c made once after an if/else, from a variable each arm set last, written in each arm instead.

When both arms of an `if` end by storing to the same place, gcc keeps the two stores, or merges them into one after the
join, depending on what each arm computed. m2c reads the merged form back as a variable each arm sets, stored once:

    if (c) {
        f();
        v = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x14;
    } else {
        g();
        v = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x1C;
    }
    M2C_FIELD(p, s32 *, 0x28) = v;

An N64 function was 99.3% this way: the shared value lived in a saved register, so the addresses loaded before a later
call came in the other order. With the store written at the end of each arm and the variable gone, it was exact.
Offered only when the variable is set nowhere but the two arms' last statements and read nowhere but the store.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'carried_store_arms'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def _last_assignment(arm, var):
    """The span (in `arm`) of a trailing `var = E;` statement, and E's span, or None."""
    hit = re.search(r'(?m)^([ \t]*)' + var + r'\s*=(?!=)\s*([^;]+);\s*$', arm)
    if not hit:
        return None
    return hit


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    result = []
    for store in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^;={}\n]+?)\s*=(?!=)\s*(?P<var>' + IDENT + r')\s*;[ \t]*\n',
                             clean[opening:end]):
        var, lhs = store['var'], store['lhs'].strip()
        if var == lhs or re.search(r'\b' + var + r'\b', lhs):
            continue
        at = opening + store.start()
        # the statement right before it is an if/else: walk back over the else arm
        before = clean[:at].rstrip()
        if not before.endswith('}'):
            continue
        else_close = len(before)
        else_open = _opening_brace(clean, else_close - 1)
        if else_open is None or not re.search(r'\belse\s*$', clean[:else_open]):
            continue
        else_kw = re.search(r'\belse\s*$', clean[:else_open]).start()
        if_close = len(clean[:else_kw].rstrip())
        if clean[if_close - 1:if_close] != '}':
            continue
        if_open = _opening_brace(clean, if_close - 1)
        if if_open is None:
            continue
        arms = [(if_open + 1, if_close - 1), (else_open + 1, else_close - 1)]
        lasts = []
        for a, b in arms:
            arm = clean[a:b]
            last = _last_assignment(arm, var)
            if not last or arm[last.end():].strip():
                lasts = None
                break
            # (only up to the statement's `;`: what follows, the arm's closing line, stays as it was)
            semicolon = arm.find(';', last.end(2)) + 1
            lasts.append((a + last.start(), a + semicolon, a + last.start(2), a + last.end(2), last.group(1)))
        if not lasts:
            continue
        # the variable appears nowhere else in the function (its declaration aside)
        mentions = [m.start() + opening for m in re.finditer(r'(?<![\w.>])' + var + r'\b', body)]
        declared = re.search(r'(?m)^[ \t]*(?:[\w ]+?)\s+\**' + var + r'\s*;[ \t]*\n', clean[opening:if_open])
        inside = [p for p in mentions if any(s <= p < e for s, e, _, _, _ in lasts)]
        others = [p for p in mentions if p not in inside and not (at <= p < opening + store.end())
                  and not (declared and opening + declared.start() <= p < opening + declared.end())]
        if len(inside) != 2 or others:
            continue
        text = source
        edits = [(opening + store.start(), opening + store.end(), '')]
        for s, e, vs, ve, indent in lasts:
            target = source[opening + store.start('lhs'):opening + store.end('lhs')].strip()
            edits.append((s, e, f'{indent}{target} = {source[vs:ve].strip()};'))
        if declared:
            edits.append((opening + declared.start(), opening + declared.end(), ''))
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        result.append((FAMILY, text))
        if len(result) >= 3:
            break
    return result


def _opening_brace(text, closing):
    depth = 0
    for pos in range(closing, -1, -1):
        depth += (text[pos] == '}') - (text[pos] == '{')
        if depth == 0:
            return pos
    return None
