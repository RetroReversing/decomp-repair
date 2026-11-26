"""An m2c break/fence ladder around a linked-list find, written as the plain do/while walk.

    p = head;                                              p = head;
    if (p != NULL) {                                       if (p != NULL) {
        r = NULL;                                              do {
        do { { void *__fence_p; ... r = __fence_p; }               if (KEY(p) == arg0) { return p; }
            __repair_entry_p = p;                  ->              p = NEXT(p);
            if (!(KEY(p) != arg0)) break;                      } while (p != NULL);
            p = NEXT(p); r = NULL;                         }
        } while (p != NULL);                               return NULL;
    }
    return r;

The ladder keeps the result in a second local, reset to NULL on every step and set when the key matches before a
`break`; KMC GCC 2.7.2 (`-O2`) then keeps both in registers and the loop's exit differs by a row or two (175 points on
a list lookup of 21 instructions). The original returned the cursor from inside the loop and NULL after it. Offered for
the exact ladder above (the fence statements between `do {` and the key test are only `__fence_`/`__repair_` helpers);
the test's `!=` becomes `==` and the helper locals go. `list_walk_ladder_unwrap`. A candidate for the exact judge."""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'list_walk_ladder_unwrap'
FAMILIES = (FAMILY,)
LADDER = re.compile(
    rf'\s*(?P<v>{IDENT})\s*=\s*(?P<head>[^;]+);\s*if\s*\(\s*(?P=v)\s*!=\s*(?P<nil>NULL|0)\s*\)\s*{{\s*(?P<r>{IDENT})\s*=\s*(?P=nil)\s*;'
    rf'\s*do\s*{{(?P<fence>.*?)if\s*\(\s*!\s*\((?P<test>[^;{{}}]+?)\)\s*\)\s*(?:{{\s*)?break\s*;\s*(?:}}\s*)?'
    rf'(?P=v)\s*=\s*(?P<next>[^;]+);\s*(?P=r)\s*=\s*(?P=nil)\s*;\s*}}\s*while\s*\(\s*(?P=v)\s*!=\s*(?P=nil)\s*\)\s*;\s*}}\s*'
    rf'return\s+(?P=r)\s*;\s*$', re.S)
LOCAL = re.compile(rf'^[ \t]*(?!return\b)(?:[A-Za-z_][\w ]*?)[ \t]+\**[ \t]*{IDENT}[ \t]*;[ \t]*\n', re.M)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    last = part.clean.rfind('}', 0, part.end)
    body = part.clean[part.opening + 1:last]
    code = LOCAL.sub('', body)
    hit = LADDER.fullmatch(code)
    if not hit or not re.search(r'__fence|__repair', hit['fence']) or re.search(r'\bif\b', hit['fence']):
        return []
    test = re.fullmatch(r'\s*(?P<a>[^!=<>&|?]+?(?:\([^;]*\))?)\s*!=\s*(?P<b>[^&|?]+?)\s*', hit['test'])
    if not test or '&&' in hit['test'] or '||' in hit['test']:
        return []
    v, nil = hit['v'], hit['nil']
    decl = re.search(rf'(?m)^[ \t]*([A-Za-z_][\w ]*?[ \t]*\*+)[ \t]*{v}[ \t]*;', body)
    if not decl:
        return []
    kind = decl[1].strip()
    new = (f'\n    {kind} {v};\n\n    {v} = {hit["head"].strip()};\n    if ({v} != {nil}) {{\n        do {{\n'
           f'            if ({test["a"].strip()} == {test["b"].strip()}) {{\n                return {v};\n            }}\n'
           f'            {v} = {hit["next"].strip()};\n        }} while ({v} != {nil});\n    }}\n    return {nil};\n')
    text = source[:part.opening + 1] + new + source[last:]
    return [(FAMILY, text)] if text != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
