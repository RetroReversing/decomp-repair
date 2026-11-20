"""Move an existing failure action before its shared cleanup label."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close
from .terminal_guard_repairs import _declarations

FAMILY = 'out_of_line_guard_failure'


def variants(source, name, header=''):
    part = view(source, name)
    if not part or max(len(source), len(header)) > 128000:
        return []
    body = part.body
    context = _blank(source + '\n' + header)
    if re.search(r'\\\r?\n|\?\?|%:|^\s*#\s*(?!define\b)\w+|\b(?:asm|__asm|__asm__|__LINE__|__COUNTER__|__label__|namespace|class|template)\b',
                 context, re.M):
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+(' + IDENT + r')', context, re.M))
    if any(re.search(r'\b' + re.escape(macro) + r'\b', body) for macro in macros):
        return []
    hit = re.search(r'\bif\s*\(', body)
    if not hit or re.search(r'[{}]|\b(?:return|goto|for|while|switch|do)\b', body[:hit.start()]):
        return []
    start = part.opening + 1
    condition = close(part.clean, start + hit.end() - 1)
    arm = re.match(r'\s*\{', part.clean[condition:]) if condition else None
    if not arm:
        return []
    brace = condition + arm.end() - 1
    end = close(part.clean, brace, '{', '}')
    if not end or re.match(r'\s*else\b', part.clean[end:]):
        return []
    failure = re.fullmatch(r'\s*([^;{}]+;)\s*goto\s+(' + IDENT + r')\s*;\s*',
                           part.clean[brace + 1:end - 1])
    if not failure or not re.search(r'(?<![!=<>])=(?!=)', failure[1]):
        return []
    if _declarations(part, brace + 1 + failure.start(1), brace + 1 + failure.end(1)):
        return []
    cleanup = list(re.finditer(r'(?m)^[ \t]*' + re.escape(failure[2]) + r'\s*:', part.clean[end:part.end]))
    if len(cleanup) != 1:
        return []
    label = end + cleanup[0].start()
    if not part.clean[end:label].strip():
        return []
    # A label must be at top level. Skipping declarations could change bindings or VLA lifetime.
    middle = part.clean[end:label]
    # goto and return are not declarations. Other statement text is checked conservatively.
    declarations = re.sub(r'\b(?:goto|return)\b[^;]*;', ';', middle)
    masked = view(source[:end] + declarations + source[label:], name)
    if not masked or _declarations(masked, end, end + len(declarations)):
        return []
    if middle.count('{') != middle.count('}') or re.search(r'\b(?:case|default|switch|try|catch)\b', middle):
        return []
    fresh = 'decomp_failure'
    while re.search(r'\b' + fresh + r'\b', context):
        fresh += '_'
    action = source[brace + 1 + failure.start(1):brace + 1 + failure.end(1)]
    return [(FAMILY, edit(source, [
        (brace + 1, end - 1, f' goto {fresh}; '),
        (label, label, f'    goto {failure[2]};\n{fresh}:\n    {action}\n'),
    ]))]
