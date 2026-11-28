"""m2c's guard whose second test sits behind a value both paths stage, written as one `&&` condition.

The compiler starts a shift or a load that follows the test in the branch's delay slot, so both paths hold it and m2c
writes it twice, with the second test between them and a `goto` round the other copy:

    if (A) {                      if ((A) && (B)) {
        t = E;                        return r;
        if (B) {                  }
            return r;     ->      t = E;
        }
        goto join;
    }
    t = E;
    join:

Both write the same program when `E` calls nothing and `B` does not read `t`. The label goes when nothing else jumps
to it.

Measured on a 485-instruction N64 texture loader (SN GCC 2.8.1 `-mfp64`): the last step no other family offered, with
the early return before it no longer a `goto`; the written-out form was 15 from the target without it and byte
identical with it. One function."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, view

FAMILY = 'guarded_stage_join'
FAMILIES = (FAMILY,)
PATTERN = re.compile(
    rf'(?P<indent>[ \t]*)if\s*\((?P<first>[^{{}};]+)\)\s*\{{\s*(?P<stage>(?P<name>{IDENT})\s*=(?!=)\s*[^{{}};]+;)'
    rf'\s*if\s*\((?P<second>[^{{}};]+)\)\s*\{{\s*(?P<leave>(?:return\b[^{{}};]*|goto\s+{IDENT}\s*);)\s*\}}'
    rf'\s*goto\s+(?P<label>{IDENT})\s*;\s*\}}\s*(?P<again>{IDENT}\s*=(?!=)\s*[^{{}};]+;)\s*(?P=label)\s*:[ \t]*')


def variants(source, name):
    part = view(source, name)
    if not part or 'goto' not in part.body:
        return []
    out = []
    for hit in PATTERN.finditer(part.clean, part.opening, part.end):
        stage, local, label = hit['stage'], hit['name'], hit['label']
        if (' '.join(stage.split()) != ' '.join(hit['again'].split())
                or re.search(rf'\b{local}\b', hit['second'])
                or re.search(rf'\b{IDENT}\s*\((?!\s*[su](?:8|16|32)\b)', stage.split('=', 1)[1])):
            continue
        indent = hit['indent']
        first = source[hit.start('first'):hit.end('first')]
        second = source[hit.start('second'):hit.end('second')]
        leave = source[hit.start('leave'):hit.end('leave')]
        keep = source[hit.start('again'):hit.end('again')]
        others = len(re.findall(rf'\bgoto\s+{label}\b', _blank(part.body))) - 1
        text = (f'{indent}if (({first}) && ({second})) {{\n{indent}    {leave}\n{indent}}}\n{indent}{keep}\n'
                + (f'{label}:\n' if others else ''))
        tail = source[hit.end():]
        out.append((FAMILY, source[:hit.start()] + text + (tail[1:] if tail.startswith('\n') else tail)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}
