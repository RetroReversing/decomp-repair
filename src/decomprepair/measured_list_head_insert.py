"""Recover a previous-head link from a target list insertion sequence."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lui \$a1, %hi\((?P<head>{IDENT})\)\naddiu \$a1, \$a1, %lo\((?P=head)\)\n'
    rf'sw \$s1, 4\(\$s0\)\nlw \$v1, \(\$a1\)\nmove \$a0, \$v0\n'
    rf'sh \$s2, 8\(\$s0\)\nsw \$v1, \(\$s0\)\n'
    rf'jal (?P<callee>{IDENT})\nsw \$s0, \(\$a1\)'
)
_SOURCE = re.compile(
    rf'(?P<word>\(\((?P<type>{IDENT})\s*\*\)\s*(?P<node>{IDENT})\)->field_4\s*=\s*(?P<arg1>{IDENT})\s*;)\s*'
    rf'(?P<half>\(\((?P=type)\s*\*\)\s*(?P=node)\)->field_8\s*=\s*(?P<arg2>{IDENT})\s*;)\s*'
    rf'(?P<head>{IDENT})\s*=\s*(?P=node)\s*;\s*'
    rf'(?P<link>\(\((?P=type)\s*\*\)\s*(?P=node)\)->field_0)\s*=\s*\(void\s*\*\)\s*(?P=head)\s*;\s*'
    rf'(?P<callee>{IDENT})\s*\(\s*(?P<saved>{IDENT})\s*,\s*&\s*(?P=head)\s*\)\s*;'
)


def variants(source, name, header, rows):
    if not 20 <= len(rows) <= 45:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    hit = _TARGET.search(target)
    if not hit:
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if (f'sw $s0, %lo({hit["head"]})($at)' not in candidate
            or 'sw $s0, ($s0)' not in candidate):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_head)\b', part.clean):
        return []
    part.end = end
    matches = list(_SOURCE.finditer(part.body))
    if len(matches) != 1:
        return []
    draft = matches[0]
    if draft['head'] != hit['head'] or draft['callee'] != hit['callee']:
        return []
    signature = (rf'\bvoid\s+{re.escape(name)}\s*\(void\s*\*\s*{re.escape(draft["node"])}\s*,\s*'
                 rf's32\s+{re.escape(draft["arg1"])}\s*,\s*s16\s+{re.escape(draft["arg2"])}\s*\)\s*$')
    if not re.search(signature, part.clean[:part.opening]):
        return []
    typedef = (rf'typedef\s+struct\s*{{\s*void\s*\*\s*field_0\s*;\s*int\s+field_4\s*;\s*'
               rf'short\s+field_8\s*;\s*}}\s*{re.escape(draft["type"])}\s*;')
    if (not re.search(typedef, part.clean[:part.opening])
            or not re.search(rf'\bextern\s+void\s*\*\s*{re.escape(draft["head"])}\s*;', part.clean[:part.opening])):
        return []
    # The extra pointer is captured before the first call; its address cannot change.
    if re.search(rf'\b{re.escape(draft["head"])}\b', part.body[:draft.start()]):
        return []
    start = part.opening + 1
    original = source[start + draft.start():start + draft.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    indent = '\n    '
    fixed_body = (draft['word'] + indent + draft['link'] + ' = (void *) *__repair_head;'
                  + indent + draft['half'] + indent + '*__repair_head = ' + draft['node'] + ';'
                  + indent + draft['callee'] + '(' + draft['saved'] + ', __repair_head);')
    # This intentionally repairs the target's ordering: the original draft self-links.
    statements = list(re.finditer(rf'\b{re.escape(draft["saved"])}\s*=\s*{re.escape(draft["callee"])}\s*\(',
                                  part.body[:draft.start()]))
    if len(statements) != 1:
        return []
    at = start + statements[0].start()
    fixed = edit(source, [(start, start, '\n    void **__repair_head;'),
                          (at, at, f'__repair_head = &{draft["head"]};\n    '),
                          (start + draft.start(), start + draft.end(), fixed_body)])
    return [('measured_list_head_insert', fixed)]
