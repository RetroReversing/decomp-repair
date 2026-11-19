"""A load m2c held in a temporary that only comparisons read, written into each comparison instead.

gcc 2.7.2 loads a comparison's operands in the order the C names them. m2c holds a field it compares more than once in
a temporary, which loads it ahead of the other operands; where the game named the other operand first, its loads came
the other way round:

    temp_fv1_5 = M2C_FIELD(arg0, f32 *, 8);
    if (M2C_FIELD(arg1, f32 *, 4) < temp_fv1_5) { if (!(M2C_FIELD(arg2, f32 *, 4) < temp_fv1_5)) ...

An N64 bounding-box test was 99.5% so; with both temporaries written into their comparisons it was 99.7%, and with
each comparison naming the other operand first (`b > a` for `a < b`) it was exact. Inlining alone or swapping alone is
no better or worse, so a search that takes one step at a time never reaches it: both forms are offered here, once each
for all such temporaries in the function. Only for a temporary assigned a plain load once and read only as one side of
`<`, `>`, `<=`, `>=`, `==`, `!=`, with nothing written in between that the load could read.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'compared_load_inline'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
FLIP = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '==': '==', '!=': '!='}
OPERAND = r'(?:M2C_FIELD\s*\([^;]*?\)|' + IDENT + r'(?:\s*->\s*' + IDENT + r')*)'


def _load(text):
    """A plain load (an M2C_FIELD read or a field access, no call), or None."""
    text = text.strip()
    if re.fullmatch(r'M2C_FIELD\s*\(.*\)', text, re.S):
        if close(text, text.find('(')) != len(text):
            return None
        calls = re.findall(r'\b(' + IDENT + r')\s*\(', text)
        return text if all(c == 'M2C_FIELD' for c in calls) else None
    if re.fullmatch(IDENT + r'(?:\s*->\s*' + IDENT + r')+', text):
        return text
    return None


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
    plans = []
    for assign in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?P<var>' + IDENT + r')\s*=(?!=)\s*(?P<rhs>[^;]+);[ \t]*\n', body):
        var = assign['var']
        load = _load(assign['rhs'])
        if not load:
            continue
        mentions = [m for m in re.finditer(r'(?<![\w.>])' + var + r'\b', body)]
        uses = [m for m in mentions if m.start() >= assign.end()]
        others = [m for m in mentions if m.start() < assign.start()]
        declared = re.search(r'(?m)^[ \t]*[\w ]+?\s+\**' + var + r'\s*;', body[:assign.start()])
        if declared:
            others = [m for m in others if not (declared.start() <= m.start() < declared.end())]
        if others or len(uses) < 1:
            continue
        sites = []
        for use in uses:
            after = re.match(r'\s*(<=|>=|==|!=|<|>)(?![<>=])\s*', body[use.end():])
            before = re.search(r'(<=|>=|==|!=|<|>)\s*$', body[:use.start()])
            if after and not re.search(r'[<>]$', body[:use.start()].rstrip()[-1:]):
                sites.append(('left', use, after))
            elif before and not re.match(r'\s*[<>=]', body[use.end():]):
                sites.append(('right', use, before))
            else:
                sites = None
                break
        if not sites:
            continue
        # nothing between the assignment and the last use may write what the load reads, or call anything
        # (a local assigned meanwhile is fine; a store through memory or a call could change what the load reads)
        region = body[assign.end():uses[-1].start()]
        calls = [c for c in re.findall(r'\b(' + IDENT + r')\s*\(', region) if c not in ('M2C_FIELD', 'if', 'while', 'for', 'switch', 'return', 'sizeof')]
        stores = [m for m in re.finditer(r'(?m)^[ \t]*(?P<lhs>[^;={}\n]+?)\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', region)
                  if not re.fullmatch(IDENT, m['lhs'].strip())]
        if calls or stores:
            continue
        source_load = source[opening + assign.start('rhs'):opening + assign.end('rhs')].strip()
        plans.append((assign, sites, source_load, declared))
    if not plans:
        return []
    result = []
    for flip in (False, True):
        edits = []
        for assign, sites, load, declared in plans:
            edits.append((opening + assign.start(), opening + assign.end(), ''))
            if declared:
                edits.append((opening + declared.start(), opening + body.find('\n', declared.start()) + 1, ''))
            for side, use, op in sites:
                if not flip or side == 'right':
                    edits.append((opening + use.start(), opening + use.end(), load))
                    continue
                # `load OP other` → `other FLIP(OP) load`: find the other operand after the operator
                other_start = opening + use.end() + op.end()
                other = re.match(OPERAND, clean[other_start:])
                if not other or (other.group(0).startswith('M2C_FIELD') and close(clean, other_start + other.group(0).find('(')) is None):
                    edits.append((opening + use.start(), opening + use.end(), load))
                    continue
                other_end = other_start + len(other.group(0))
                if other.group(0).startswith('M2C_FIELD'):
                    other_end = close(clean, other_start + other.group(0).find('('))
                text_other = source[other_start:other_end]
                edits.append((opening + use.start(), other_end, f'{text_other} {FLIP[op.group(1)]} {load}'))
        text = source
        for a, b, new in sorted(set(edits), key=lambda e: (e[0], e[1]), reverse=True):
            text = text[:a] + new + text[b:]
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result
