"""Recover a measured count-pointer access around a linked-list loop latch."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close
from .permuter_macro_effects import DEFINE

FAMILY = 'measured_loop_count_pointer'
FAMILIES = (FAMILY,)

WRAPPER = re.compile(
    r'/\*__repair_loop_weight\*/__repair_rows:\s*\{\s*do\s*\{\s*do\s*\{\s*'
    rf'(?P<index>{IDENT})\s*\+=\s*1\s*;\s*\}}\s*while\s*\(\s*0\s*\)\s*;\s*'
    r'\}\s*while\s*\(\s*0\s*\)\s*;\s*\}\s*if\s*\(\s*0\s*\)\s*goto\s+__repair_rows\s*;'
)
BASE = re.compile(rf'M2C_FIELD\(\s*&\s*(?P<state>{IDENT})\s*,\s*void\s*\*\s*\*\s*,\s*'
                  rf'(?P<offset>{NUMBER})\s*\)')


def variants(source, name, header, rows, flags, resolve):
    flags = set(flags or ())
    if not resolve or not flags.intersection({'-mgp32', '-mabi=32'}) or flags.intersection(
            {'-m64', '-mgp64', '-mabi=64', '-mabi=n32', '-mabi=eabi'}):
        return []
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    pattern = re.compile(
        rf'lui \$v0, %hi\((?P<global>{IDENT})\)\nlw \$v0, %lo\((?P=global)\)\(\$v0\)\n'
        rf'addiu (?P<index>\$s[0-7]), (?P=index), 1\nlhu \$v1, (?P<count>\d+)\(\$v0\)\n'
        rf'lw (?P<node>\$s[0-7]), \((?P=node)\)\nandi \$v0, (?P=index), 255\nsltu \$v0, \$v0, \$v1'
    )
    witness = pattern.search(target)
    if not witness or witness['index'] == witness['node']:
        return []
    expected = (f'addiu {witness["index"]}, {witness["index"]}, 1\n'
                f'lw {witness["node"]}, ({witness["node"]})\n'
                f'lui $v0, %hi({witness["global"]})\nlw $v0, %lo({witness["global"]})($v0)\n'
                f'lhu $v1, {witness["count"]}($v0)')
    if expected not in candidate:
        return []
    original = view(source, name)
    if not original:
        return []
    original_end = close(original.clean, original.opening, '{', '}')
    if not original_end:
        return []
    raw_body = source[original.opening + 1:original_end - 1]
    wrappers = list(WRAPPER.finditer(raw_body))
    if wrappers:
        if len(wrappers) != 1 or raw_body.count('__repair_rows') != 2:
            return []
        wrapper = wrappers[0]
        raw_body = raw_body[:wrapper.start()] + '\n            ' + wrapper['index'] + ' += 1;' + raw_body[wrapper.end():]
        source = source[:original.opening + 1] + raw_body + source[original_end - 1:]
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    span = find(source, name)
    if not end or not span or not re.fullmatch(r'\s*void\s+' + re.escape(name) + r'\s*\(\s*void\s*\)\s*',
                                                part.clean[span[0]:part.opening]):
        return []
    body = part.clean[part.opening + 1:end - 1]
    if re.search(r'\b(?:volatile|asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__)\b|(?m:^\s*#)', body):
        return []
    if re.search(r'/\*|//', source[part.opening + 1:end - 1]):
        return []
    tail = re.search(
        rf'(?P<index>{IDENT})\s*\+=\s*1\s*;\s*(?P<node>{IDENT})\s*=\s*M2C_FIELD\(\s*(?P=node)\s*,\s*'
        rf'void\s*\*\s*\*\s*,\s*0\s*\)\s*;\s*\}}\s*while\s*\(\s*\(u32\)\s*\(\s*(?P=index)\s*&\s*'
        rf'(?P<mask>{NUMBER})\s*\)\s*<\s*\(u16\)\s*M2C_FIELD\(\s*'
        rf'(?P<base>M2C_FIELD\(\s*&\s*(?P<state>{IDENT})\s*,\s*void\s*\*\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\))'
        rf'\s*,\s*u16\s*\*\s*,\s*(?P<count>{NUMBER})\s*\)\s*\)\s*;', body)
    if not tail or integer(tail['mask']) != 255 or integer(tail['count']) != int(witness['count']):
        return []
    if not re.search(r'(?m)^\s*s32\s+' + re.escape(tail['index']) + r'\s*;', body):
        return []
    if not re.search(r'(?m)^\s*void\s*\*\s*' + re.escape(tail['node']) + r'\s*;', body):
        return []
    baseaddr, globaladdr = resolve(tail['state']), resolve(witness['global'])
    if baseaddr is None or globaladdr != baseaddr + integer(tail['offset']):
        return []
    bases = list(BASE.finditer(body))
    if len(bases) < 2 or any(b['state'] != tail['state'] or integer(b['offset']) != integer(tail['offset']) for b in bases):
        return []
    # The same location is only read. Replacing its m2c base+offset spelling
    # with its verified external pointer name leaves each access in place.
    for b in bases:
        if re.search(r'&\s*$', body[:b.start()]) or re.match(r'\s*(?:=(?!=)|[+*/%&|^-]=|\+\+|--)', body[b.end():]):
            return []
    context = _blank(header + '\n' + source)
    fresh, symbol = '__repair_count_ptr', witness['global']
    if re.search(r'\b(?:' + re.escape(fresh) + '|' + re.escape(symbol) + r')\b', context):
        return []
    if not re.search(r'\bextern\s+M2C_UNK\s+' + re.escape(tail['state']) + r'\s*;', context):
        return []
    if re.search(r'\b(?:void|char|s32|u32|int)\s*\*?\s+' + re.escape(tail['state']) + r'\s*[;=,]', body):
        return []
    for typ, expected_type in [('s8', r'(?:signed\s+)?char'), ('u16', r'unsigned\s+short(?:\s+int)?'),
                               ('s32', r'(?:signed\s+)?int'), ('u32', r'unsigned\s+int'), ('M2C_UNK', r's32')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected_type, aliases[0].strip()):
            return []
    definitions = list(DEFINE.finditer(re.sub(r'\\\r?\n', ' ', context)))
    protected = {tail['state'], tail['index'], tail['node'], symbol, fresh, 's8', 'u16', 's32', 'u32', 'M2C_UNK'}
    if any(m[1] in protected for m in definitions):
        return []
    used = set(re.findall(IDENT, body)) | {tail['state'], symbol, fresh, 'u16', 's8'}
    for macro in definitions:
        if macro[1] not in used:
            continue
        if macro[1] == 'M2C_FIELD':
            if macro[2] != '(expr, type_ptr, offset)' or re.sub(r'\s+', '', macro[3]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
                return []
        elif macro[2] is not None or not re.fullmatch(r'\s*\(*\s*(?:\(\s*void\s*\*\s*\)\s*)?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*\)*\s*', macro[3]):
            return []
    if sum(m[1] == 'M2C_FIELD' for m in definitions) != 1:
        return []
    if re.search(r'(?m)^\s*#\s*undef\s+(' + '|'.join(map(re.escape, protected | {'M2C_FIELD'})) + r')\b', context):
        return []
    count = re.compile(r'M2C_FIELD\(\s*' + re.escape(tail['base']) + r'\s*,\s*u16\s*\*\s*,\s*'
                       + re.escape(tail['count']) + r'\s*\)')
    counts = list(count.finditer(body))
    if len(counts) != 2 or not counts[0].start() < tail.start() < counts[1].start():
        return []
    insertion = (f'extern void *{symbol};\n'
                 f'static inline u16 *{fresh}(void *p) {{ return (u16 *)((char *)p + {tail["count"]}); }}\n')
    prefix = part.clean.rfind('\n', 0, span[0]) + 1
    if part.clean[prefix:span[0]].strip():
        return []
    results = []
    for chosen in (counts, counts[:1]):
        edits = [(prefix, prefix, insertion)]
        covered = [(c.start(), c.end()) for c in chosen]
        edits += [(part.opening + 1 + c.start(), part.opening + 1 + c.end(), f'(*{fresh}({symbol}))') for c in chosen]
        edits += [(part.opening + 1 + b.start(), part.opening + 1 + b.end(), symbol) for b in bases
                  if not any(a <= b.start() and b.end() <= z for a, z in covered)]
        results.append((FAMILY, edit(source, edits)))
    return results
