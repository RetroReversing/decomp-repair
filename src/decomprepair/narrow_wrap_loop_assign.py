"""A narrow local wrapped into range by a loop, written with its unsigned twin assigned in the loop's test.

An angle is brought into range as

    angle = offset + (direction(dx, dy) + 0xC00);
    while (angle < 0) {
        angle += 0x1000;
    }

with `angle` an `s16`. GCC copies the test ahead of the loop, so the target's shape does not come out: one test at the
loop's head (`move $s0, $v0; sll $v0, $v0, 16; bltzl $v0, head; addiu $v0, $s0, 0x1000`), where the value that goes
round is the unsigned one in `$v0` and the narrow local is a copy of it:

    u16 wrap_angle;
    wrap_angle = offset + (direction(dx, dy) + 0xC00);
    while ((angle = wrap_angle) < 0) {
        wrap_angle = angle + 0x1000;
    }

Both compute the same values: the local is the low half of the twin each time. On a 113-instruction N64 turning
routine (SN GCC 2.8.1, `-O2`) whose registers were already right the plain loop scored 620 and this form 0.

wrap_loop_test_assignment
    Each such loop of an `s16`/`s8` local (also in m2c's `label: if (v < K) { v += K2; goto label; }` form), with the
    step written from the narrow local; a second child steps the twin itself (`t += K`).
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'wrap_loop_test_assignment'
FAMILIES = (FAMILY,)
LIMIT = 8
_UNSIGNED = {'s16': 'u16', 'short': 'u16', 's8': 'u8', 'signed char': 'u8'}
_TEST = rf'(?P<name>{IDENT})\s*(?P<op><=|>=|<|>)\s*(?P<bound>-?\s*{NUMBER})'
_STEP = (rf'(?P=name)\s*(?:(?P<compound>\+|-)=\s*|=\s*(?P=name)\s*(?P<plain>\+|-)\s*)(?P<step>{NUMBER})\s*;')
_WHILE = re.compile(rf'(?<![\w.])while\s*\(\s*{_TEST}\s*\)\s*(?:\{{\s*{_STEP}\s*\}}|{_STEP.replace("compound", "bare_compound").replace("plain", "bare_plain").replace("step", "bare_step")})')
_GOTO = re.compile(rf'(?<![\w.?:])(?P<label>{IDENT})\s*:\s*if\s*\(\s*{_TEST}\s*\)\s*\{{\s*{_STEP}\s*'
                   rf'goto\s+(?P=label)\s*;\s*\}}')
_SET = re.compile(rf'(?<![\w.>*\]])(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}]+);\s*$')


def _declaration(part, name):
    kinds = '|'.join(_UNSIGNED)
    return re.search(rf'(?<![\w])(?P<kind>{kinds})\s+{re.escape(name)}\s*;', part.clean[part.opening:part.end])


def _loops(part, name):
    for pattern in (_WHILE, _GOTO):
        for hit in pattern.finditer(part.clean, part.opening, part.end):
            local = hit['name']
            declared = _declaration(part, local)
            before = _SET.search(part.clean, part.opening, hit.start())
            if not declared or not before or before['name'] != local:
                continue
            if part.clean[:before.start()].rstrip()[-1:] not in (';', '{', '}'):
                continue  # `if (x) v = E;`: the twin would be unset on the other path
            if pattern is _GOTO and len(re.findall(rf'\bgoto\s+{hit["label"]}\b', part.clean)) != 1:
                continue
            groups = hit.groupdict()
            sign = groups.get('compound') or groups.get('plain') or groups.get('bare_compound') or groups.get('bare_plain')
            step = groups.get('step') or groups.get('bare_step')
            yield hit, declared, before, local, sign, step


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for hit, declared, before, local, sign, step in list(_loops(part, name))[:LIMIT // 2]:
        twin = f'wrap_{local}'
        if re.search(rf'\b{twin}\b', part.clean):
            continue
        value = part.source[before.start('value'):before.end('value')].strip()
        indent = part.source[part.source.rfind('\n', 0, hit.start()) + 1:hit.start()]
        indent = indent if not indent.strip() else '    '
        bound = ''.join(hit['bound'].split())
        declare = part.opening + declared.end()
        for step_line in (f'{twin} = {local} {sign} {step};', f'{twin} {sign}= {step};'):
            loop = (f'while (({local} = {twin}) {hit["op"]} {bound}) {{\n'
                    f'{indent}    {step_line}\n{indent}}}')
            out.append((FAMILY, edit(part.source, [
                (declare, declare, f'\n    {_UNSIGNED[declared["kind"]]} {twin};'),
                (before.start(), before.end(), f'{twin} = {value};\n{indent}'),
                (hit.start(), hit.end(), loop)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
