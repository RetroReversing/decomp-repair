"""Offer extra allocation weight for a real indexed load in a backward-goto loop.

For a MIPS GCC 2.7 state handler, four one-shot scopes around a post-call
load changed register priorities and improved an O1 diagnostic from 7215 to
7120. These scopes are compiler scaffolding; the judge decides each child.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'goto_load_weight'
LIMIT = 120


def variants(source, name, header='', flags=None):
    if any(f.startswith(('-D', '-include', '-imacros', '-Wp,', '-Xpreprocessor', '@')) for f in flags or ()):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end]
    combined = source + '\n' + header
    if re.search(r'(?m)^\s*#\s*(?:include(?:_next)?|import)\b', combined):
        return []
    if re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b', body):
        return []
    directives = '\n'.join(re.findall(r'(?m)^\s*#.*(?:\\\n.*)*', combined))
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})\b', directives))
    if {'do', 'while'} & macros:
        return []
    result = []
    labels = re.compile(rf'(?m)^[ \t]*(?P<label>{IDENT})\s*:\s*\{{')
    for label in labels.finditer(clean, part.opening + 1, part.end):
        if label['label'] in ('case', 'default'):
            continue
        opening = label.end() - 1
        end = close(clean, opening, '{', '}')
        if not end or not re.search(rf'\bgoto\s+{re.escape(label["label"])}\s*;', clean[end:part.end]):
            continue
        pattern = rf'(?m)^[ \t]*(?P<lhs>{IDENT})\s*=\s*\*\s*\(\s*(?P<base>{IDENT})\s*\+\s*(?P<index>{IDENT})\s*\)\s*;'
        for m in re.finditer(pattern, clean[opening + 1:end - 1]):
            start = opening + 1 + m.start()
            stop = opening + 1 + m.end()
            if {m['lhs'], m['base'], m['index']} & macros:
                continue
            if clean[opening + 1:start].rstrip()[-1:] not in ('', ';', '{', '}'):
                continue  # an unbraced statement or a label could govern this line
            text = source[start:stop].strip()
            indent = re.match(r'[ \t]*', source[start:stop])[0]
            for depth in (2, 3, 4):
                replacement = indent + 'do { ' * depth + text + ' } while (0);' * depth
                result.append((FAMILY, edit(source, [(start, stop, replacement)])))
                if len(result) >= LIMIT:
                    return result
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'header', 'flags'),
          'archs': ('mips',)}
