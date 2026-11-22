"""Compare a saved signed byte and recover the original stack reservation."""

import re

from .balanced_signed_selector_increment import _HELPER
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for
from .operand_lifetime_repairs import _visible
from .pattern_repairs import close
from .phase_projection_holders import _SLOT

FAMILY = 'balanced_signed_reset_copy'
_ADDR = r'\s*\(\(\(char\s*\*\)\s*(?P=base)\)\s*\+\s*'
_SITE = re.compile(
    rf'(?m)^[ \t]*(?P<sample>{IDENT})\s*=\s*(?P<read>{IDENT})'
    rf'\(\s*\(char\s*\*\)\s*(?P<base>{IDENT})\s*,\s*(?P<sample_offset>{NUMBER})\s*\)\s*;\s*\n'
    rf'(?P<reset>[ \t]*\*\(\(u8\s*\*\){_ADDR}(?P<reset_offset>{NUMBER})\)\s*\))'
    rf'\s*=\s*(?P<value>{NUMBER})\s*;[ \t]*\n'
    rf'(?P<copy_line>[ \t]*(?P<copy>{IDENT})\s*=\s*(?P=sample)\s*;[ \t]*\n)'
    rf'(?P<comparison>[ \t]*(?P=sample)\s*=\s*\(\s*(?P<other>(?P=sample))'
    rf'\s*<\s*(?P<limit>{NUMBER})\s*\)\s*;[ \t]*\n)'
    rf'[ \t]*if\s*\(\s*(?P=sample)\s*\)\s*{{\s*'
    rf'\*\(\(s8\s*\*\){_ADDR}(?P<stored_offset>{NUMBER})\)\s*\)\s*=\s*'
    rf'\(s8\)\s*\(\s*(?P=copy)\s*\+\s*1\s*\)\s*;\s*}}'
)
_RESET_REG = re.compile(rf'addiu \$v0, \$zero, ({NUMBER})')
_COUNT_READ = re.compile(rf'lb \$v0, ({NUMBER})(\(\$\w+\))')
_SAMPLE_READ = re.compile(rf'lb \$v1, ({NUMBER})(\(\$\w+\))')
_COMPARE = re.compile(rf'slti \$v1, \$v1, ({NUMBER})')


def _witnesses(rows):
    linked = [(expected, actual) for _, expected, actual in rows if expected]
    for i, (expected, actual) in enumerate(linked[2:-7], 2):
        reset = _RESET_REG.fullmatch(expected)
        sample = _SAMPLE_READ.fullmatch(linked[i + 1][0])
        count = _COUNT_READ.fullmatch(linked[i - 2][0])
        cmp = _COMPARE.fullmatch(linked[i + 4][0])
        guard, predicate = linked[i - 1], linked[i + 5]
        if (not reset or not sample or not count or not cmp or count[2] != sample[2]
                or actual != f'addiu $v1, $zero, {reset[1]}' or linked[i - 2][0] != linked[i - 2][1]
                or not guard[0].startswith('bgez $v0, ') or guard[0] != guard[1]):
            continue
        if (
            linked[i + 1][1] == f'lb $v0, {sample[1]}{sample[2]}'
            and linked[i + 2] == (f'sb $v0, {count[1]}{count[2]}', f'sb $v1, {count[1]}{count[2]}')
            and linked[i + 3] == ('move $v0, $v1', 'move $v1, $v0')
            and linked[i + 4][1] == f'slti $v0, $v0, {cmp[1]}'
            and predicate[0].startswith('beqz $v1, ')
            and predicate[1] == predicate[0].replace('$v1', '$v0', 1)
            and linked[i + 6] == ('addiu $v0, $v0, 1', 'addiu $v0, $v1, 1')
            and linked[i + 7] == (f'sb $v0, {sample[1]}{sample[2]}',) * 2
        ):
            yield tuple(integer(match[1]) for match in (count, sample, reset, cmp))


def _unused_trailing_word(part, macros):
    proposals = []
    for field in _SLOT.finditer(part.clean, part.opening + 1, part.end):
        holder, word = field['frame'], field['slot']
        if ({holder, word} & macros or len(re.findall(rf'\b{word}\b', part.body)) != 1
                or len(re.findall(rf'\b{holder}\b(?!\s*\.)', part.body)) != 1):
            continue
        brace = part.clean.index('}', field.start())
        opens = (part.opening + match.end() - 1
                 for match in re.finditer(r'\bstruct\s*{', part.clean[part.opening:field.start()]))
        if not any(close(part.clean, opening, '{', '}') == brace + 1 for opening in opens):
            continue
        stop = part.clean.find('\n', field.start())
        if stop < 0 or not re.fullmatch(r'[ \t]*volatile\s+float\s+' + word + r'\s*;[ \t]*',
                                       part.clean[field.start():stop]):
            continue
        proposals.append((field.start(), stop + 1, ''))
    return proposals[0] if len(proposals) == 1 else None


def variants(source, name, rows, *, header='', max_bytes=65536):
    witnesses = set(_witnesses(rows))
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    macros = set(re.findall(rf'(?m)^\s*#\s*(?:define|undef)\s+({IDENT})', context))
    kinds = {'s8': {'signed char'}, 'u8': {'unsigned char'},
             's16': {'signed short', 'short', 'signed short int', 'short int'}}
    if macros & kinds.keys() or any(' '.join(typ.split()) not in kinds[alias] for typ, alias in
                                    re.findall(r'\btypedef\s+([^;{}]+?)\s+(s8|u8|s16)\s*;', context)):
        return []
    word = _unused_trailing_word(part, macros)
    if not word:
        return []
    decls = {decl['name']: decl for decl in locals_for(part)}
    readers = {match['fn'] for match in _HELPER.finditer(context)}
    candidates = []
    for site in _SITE.finditer(part.clean, part.opening + 1, part.end):
        sample, copy = decls.get(site['sample']), decls.get(site['copy'])
        if (not sample or sample['type'] not in {'s8', 'signed char'} or not copy
                or copy['type'] not in {'s16', 'short', 'signed short'} or site['read'] not in readers
                or macros & set(re.findall(IDENT, site[0]))):
            continue
        needed = tuple(integer(site[token]) for token in ('reset_offset', 'sample_offset', 'value', 'limit'))
        if needed not in witnesses or needed[1] != integer(site['stored_offset']):
            continue
        reset_start, copy_start = site.start('reset'), site.start('copy_line')
        compare_start, compare_end = site.span('comparison')
        left, right = site.span('other')
        staged = (source[copy_start:compare_start] + source[compare_start:left]
                  + site['copy'] + source[right:compare_end] + source[reset_start:copy_start])
        candidate = edit(source, [word, (reset_start, compare_end, staged)])
        if len(candidate.encode()) <= max_bytes:
            candidates.append((FAMILY, candidate))
    return candidates if len(candidates) == 1 else []
