"""Route a shared 0/1 comparison return directly to two constant exits."""
import re

from .integer_repair_support import IDENT, edit
from .pattern_repairs import close
from .residual_source_repairs import part_for

FAMILY = 'shared_fp_return'


def _comparison(expr):
    expr = expr.strip()
    while expr.startswith('(') and close(expr,0) == len(expr):
        expr = expr[1:-1].strip()
    depth = 0
    outer = []
    for char in expr:
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0:
            outer.append(char)
    text = ''.join(outer)
    return (not re.search(r'[?,|&]|(?<![<>])=',text)
            and len(re.findall(r'(?<![<>])(?:<=|>=|<|>)(?![<>])',text)) == 1)


def variants(source, name, header=''):
    """Keep each comparison intact and rewrite all paths into the shared return together."""
    part = part_for(source, name, header)
    if not part or not (closing := close(part.clean, part.opening, '{', '}')):
        return []
    start = part.opening+1
    body = part.clean[start:closing-1]
    end = re.search(
        rf'^\s*(?P<label>{IDENT})\s*:\s*return\s*\(?\s*(?P<flag>{IDENT})\s*\)?'
        r'\s*\?\s*\(?\s*1\s*\)?\s*:\s*\(?\s*0\s*\)?\s*;\s*$',
        body, re.M,
    )
    if not end:
        return []
    flag, label = end['flag'], end['label']
    yes, no = '__repair_fp_yes', '__repair_fp_no'
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')\b', source+'\n'+header, re.M))
    if macros & {flag, label, 'if', 'goto', 'else', 'return'} or any(
            re.search(rf'\b{word}\b', source+'\n'+header) for word in (yes,no)):
        return []
    declaration = list(re.finditer(rf'(?m)^[ \t]*(?:s32|int)\s+{flag}\s*;', body))
    if len(declaration) != 1:
        return []
    before = body[:end.start()]
    pattern = re.compile(rf'(?<=[;{{}}])\s*\b{flag}\s*=\s*(?P<expr>[^;{{}}]+);'
                         rf'(?P<jump>\s*goto\s+{label}\s*;)?')
    sites = list(pattern.finditer(before))
    if not 2 <= len(sites) <= 6 or not all(s['jump'] for s in sites[:-1]):
        return []
    if sites[-1]['jump'] or before[sites[-1].end():].strip():
        return []
    if (len(re.findall(rf'\b{flag}\b', body)) != len(sites)+2
            or len(re.findall(rf'\b{label}\b', body)) != len(sites)):
        return []
    # The caller supplies FP instruction evidence. Refuse arbitrary truth-valued expressions.
    if any(not _comparison(s['expr']) for s in sites):
        return []
    edits = [(start+declaration[0].start(),start+declaration[0].end(),'')]
    for site in sites:
        a,b = site.span('expr')
        expr = source[start+a:start+b]
        edits.append((start+site.start(),start+site.end(),f'\n    if ({expr}) goto {yes}; else goto {no};'))
    edits.append((start+end.start(),start+end.end(),f'\n{no}: return 0;\n{yes}: return 1;\n'))
    return [(FAMILY, edit(source, edits))]
