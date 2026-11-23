"""A pointer a call returned, tested for NULL and used throughout the arm that follows, copied into a local of its own.

m2c keeps one variable for the call's result and uses it everywhere, the test included:

    temp_v0 = make(0);                          temp_v0 = make(0);
    *((void **) (rec + 0x514)) = temp_v0;       *((void **) (rec + 0x514)) = temp_v0;
    if (temp_v0 != NULL) {                      if (temp_v0 != NULL) {
        link(temp_v0);                              obj = temp_v0;
        temp_v0->x = ...                            link(obj);   obj->x = ...

The result is a register the call defines, dead after the test; the arm's uses want a saved register of their own, and the
target moves the result there only on the path that takes the arm (`beqz $v0, ...` with the store in its delay slot,
then `move $s0, $v0`) where the one variable copies it before the test. On a 1133-instruction effect spawner a constructor
call's result was the arm's base for twenty stores: the one edit, 5630 -> 5560.

Offered for each `if (v != NULL)` / `if (v)` whose v is a declared pointer local set by a call in one of the four
statements before it, when the arm uses v at least twice and never assigns it: the copy is the arm's first statement and
the arm reads it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'call_result_arm_local'
FAMILIES = (FAMILY,)
LIMIT = 4
IDENT = r'[A-Za-z_]\w*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    result = []
    for hit in re.finditer(r'\bif\s*\(\s*(' + IDENT + r')\s*(?:!=\s*(?:NULL|0)\s*)?\)\s*\{', clean[opening:end]):
        var = hit[1]
        arm_open = opening + hit.end() - 1
        arm_close = close(clean, arm_open, '{', '}')
        declaration = re.search(r'(?m)^[ \t]*((?:const\s+)?[A-Za-z_][\w ]*?\s*\*+)[ \t]*' + re.escape(var) + r'\s*;', clean[opening:end])
        if not arm_close or not declaration:
            continue
        before = clean[max(opening, opening + hit.start() - 600):opening + hit.start()]
        statements = [s for s in before.split(';') if s.strip()][-4:]
        if not any(re.search(r'(?<![\w.>])' + re.escape(var) + r'\s*=\s*' + IDENT + r'\s*\(', s) for s in statements):
            continue
        body = clean[arm_open + 1:arm_close - 1]
        uses = re.findall(r'(?<![\w.>])' + re.escape(var) + r'\b(?!\s*=(?!=))', body)
        if len(uses) < 2 or re.search(r'(?<![\w.>])' + re.escape(var) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body) \
                or re.search(r'&\s*' + re.escape(var) + r'\b', body):
            continue
        local = f'{var}_arm'
        if re.search(r'\b' + local + r'\b', source):
            continue
        text = source[arm_open + 1:arm_close - 1]
        text = re.sub(r'(?<![\w.>])' + re.escape(var) + r'\b', local, text)
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, arm_open) + 1:])[0] + '    '
        decl_end = opening + declaration.end()
        pointer_type = declaration[1].strip()
        decl_indent = re.match(r'[ \t]*', clean[opening + declaration.start():])[0]
        edited = (source[:decl_end] + f'\n{decl_indent}{pointer_type}{local};' + source[decl_end:arm_open + 1]
                  + f'\n{indent}{local} = {var};' + text + source[arm_close - 1:])
        result.append((FAMILY, edited))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
