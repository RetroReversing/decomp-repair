"""Preserve the tests and reads while changing a small loop's source layout."""

import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, plain_repair_view, refs
from .pattern_repairs import close
from .pointer_pair_repairs import declarations

FIRST_READ = 'staged_table_entry_read'
SENTINEL = 'sentinel_test_loop'
GUARD_INIT = 'guard_delay_slot_initializer'


def first_read(source, name, header):
    part = plain_repair_view(source, name, header)
    if not part:
        return []
    types = {p['name']:p['type'] for p in declarations(part)}
    setup = re.compile(rf'(?P<first>{IDENT})\s*=(?!=)\s*&?{IDENT}\s*;\s*'
                       rf'(?P<second>{IDENT})\s*=(?!=)\s*&?{IDENT}\s*;\s*'
                       r'if\s*\(\s*(?P<read>\*\s*(?P=first))(?=\s*(?:(?:!=|==)\s*(?:0|NULL)\s*)?\))')
    options = []
    for hit in setup.finditer(part.clean, part.opening+1, part.end-1):
        first, second = hit['first'], hit['second']
        if first == second or first not in types or second not in types:
            continue
        if block_path(part, hit.start()) != [part.opening]:
            continue
        if part.clean[part.opening+1:hit.start()].rstrip()[-1:] not in ('', ';'):
            continue
        pos = part.clean.index(';', hit.start(), hit.end())+1
        token = fresh(source, header, 'repair_first_entry')
        entry_type = types[first].rstrip()[:-1].rstrip()
        options.append((FIRST_READ, edit(source, [
            (part.opening+1, part.opening+1, f'\n    {entry_type} {token};'),
            (pos, pos, f' {token} = *{first};'),
            (*hit.span('read'), token),
        ])))
        if len(options) == 2:
            break
    return options


def sentinel_loop(source, name, header, values):
    part = plain_repair_view(source, name, header)
    if not part:
        return []
    opening = re.compile(rf'(?P<value>{IDENT})\s*=\s*\*\s*(?P<ptr>{IDENT})\s*;\s*'
                         rf'if\s*\(\s*(?P=value)\s*!=\s*(?P<sentinel>{NUMBER})\s*\)\s*'
                         r'{\s*do\s*{')
    options = []
    scalars = {decl['name'] for decl in locals_for(part)}
    pointers = {decl['name'] for decl in declarations(part)}
    for hit in opening.finditer(part.clean, part.opening+1, part.end-1):
        prefix = part.clean[part.opening+1:hit.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        value, ptr, literal = hit['value'], hit['ptr'], hit['sentinel']
        if value not in scalars or ptr not in pointers or integer(literal) not in values:
            continue
        end = close(part.clean, hit.end()-1, '{', '}')
        if not end:
            continue
        tail = re.match(rf'\s*while\s*\(\s*{value}\s*!=\s*({NUMBER})\s*\)\s*;\s*}}(?!\s*else\b)',
                        part.clean[end:part.end])
        load = re.search(rf'\b{value}\s*=\s*\*\s*{ptr}\s*;\s*$', part.clean[hit.end():end-1])
        if not tail or integer(tail[1]) != integer(literal) or not load:
            continue
        if block_path(part, hit.end()+load.start()) != [*block_path(part, hit.end()-1),hit.end()-1]:
            continue
        body = source[hit.end():hit.end()+load.start()]
        if re.search(r'\b(?:continue|switch|case)\b|\w\s*:', part.clean[hit.end():hit.end()+load.start()]):
            continue
        options.append((SENTINEL, edit(source, [
            (hit.start(), end+tail.end(), f'while (({value} = *{ptr}) != {literal}) {{{body}}}'),
        ])))
        if len(options) == 2:
            break
    return options


def guarded_initializer(source, name, header, values):
    part = plain_repair_view(source, name, header)
    if not part:
        return []
    locals_ = {decl['name']:decl for decl in locals_for(part)}
    options = []
    for hit in re.compile(r'\bif\s*\(').finditer(part.clean, part.opening+1, part.end-1):
        prefix = part.clean[part.opening+1:hit.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        condition_end = close(part.clean, hit.end()-1)
        init = re.match(rf'\s*{{\s*(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>{NUMBER})\s*;'
                        r'(?=\s*(?:for|while|do)\b)', part.clean[condition_end:part.end]) if condition_end else None
        if not init or integer(init['value']) not in values:
            continue
        counter = init['name']
        brace = part.clean.index('{', condition_end)
        end = close(part.clean, brace, '{', '}')
        decl = locals_.get(counter)
        if not end or decl is None or decl.end() > hit.start():
            continue
        if block_path(part, decl.start()) != block_path(part, hit.start()):
            continue
        if any(not brace < ref.start() < end for ref in refs(part, decl)):
            continue
        start = condition_end + init.start('name')
        stop = condition_end + init.end()
        options.append((GUARD_INIT, edit(source, [
            (hit.start(), hit.start(), source[start:stop]+' '),
            (start, stop, ''),
        ])))
        if len(options) == 2:
            break
    return options
