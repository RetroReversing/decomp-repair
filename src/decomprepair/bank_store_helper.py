"""A two-table store written once as an inline helper and called where it was.

A game that keeps its controller words in a banked table and a default table stores one byte through the same test
everywhere: `if (bank != 0xFF) { banks[bank][row][i] = v & 0x7F; } else { fallback[row][i] = v & 0x7F; }`. m2c writes the
test out at each store (or, once a search has had it, through identity wrappers); the game wrote it once. A handler that
stores the coarse and the fine half of a 14-bit value in each of four `if` arms has eight copies. Written as one helper
with the arguments passed in (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) the arms' tails pair differently: the
first store's two arms share one tail after the join, the second store keeps one store per arm with its mask in the
branch's delay slot. On a 239-instruction handler this took 3530 -> 0, where each of the eight copies tried alone
changed nothing. The mask had to be kept at the second call of each pair and left to the helper at the first
(stripping every mask 9025, keeping every mask 6995; hypothesis: a mask in a call argument is computed before the
branch, the helper's after it).

`variants` finds the statement `if (B != K) { A[B]REST = E; } else { C REST = E; }` (either arm first, braces or not;
REST the same bracketed indexes in both arms) at least twice with the same `A`, `C`, `K` and number of indexes, writes
`inline static void NAME(u8 index..., u8 b, u8 v)` before the function and replaces each statement with a call. The
parameters are `u8`: an `int` helper changed the instruction count (12580). Children by what happens to a common
`& M` mask on the stored value: every call passes the value and the helper stores it, the helper masks and every call
drops its mask, and the helper masks and only the calls whose value is a shift (a word's coarse half) drop theirs.
The judge decides each child.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'bank_store_helper'
FAMILIES = (FAMILY,)
HELPER = 'store_by_bank'
MINIMUM = 2
LITERAL = r'(?:0[xX][0-9a-fA-F]+|\d+)'
MASKED = re.compile(rf'^(?P<value>.+?)\s*&\s*(?P<mask>{LITERAL})$', re.S)
STATEMENT = re.compile(
    rf'\bif\s*\(\s*(?P<bank>{IDENT})\s*(?P<op>!=|==)\s*(?P<key>{LITERAL})\s*\)\s*'
    r'(?:\{\s*(?P<first>[^{};]+?)\s*;\s*\}|(?P<first_bare>[^{};]+?)\s*;)\s*else\s*'
    r'(?:\{\s*(?P<second>[^{};]+?)\s*;\s*\}|(?P<second_bare>[^{};]+?)\s*;)')


def _indexes(text):
    """`name[a][b]` as (name, ['a', 'b']), or None when it is anything else."""
    head = re.match(rf'\s*({IDENT})\s*(?=\[)', text)
    if not head:
        return None
    found, at = [], head.end()
    while at < len(text) and text[at] == '[':
        stop = close(text, at, '[', ']')
        if not stop:
            return None
        found.append(text[at + 1:stop - 1].strip())
        at = stop
        while at < len(text) and text[at].isspace():
            at += 1
    return (head[1], found) if at == len(text) and found else None


def _assignment(text):
    left, sep, right = text.partition('=')
    if not sep or right.startswith('=') or left.rstrip()[-1:] in '!<>=+-*/&|^%':
        return None
    return left.strip(), right.strip()


def _site(hit):
    """One statement as a dict, or None when it is not the shape."""
    arms = [_assignment(hit[n] or hit[n + '_bare']) for n in ('first', 'second')]
    if not all(arms) or arms[0][1] != arms[1][1]:
        return None
    banked, plain = (_indexes(a[0]) for a in arms)
    if hit['op'] == '==':
        banked, plain = plain, banked
    if not banked or not plain:
        return None
    (table, with_bank), (fallback, rest) = banked, plain
    if not with_bank or with_bank[0].replace(' ', '') != hit['bank'] or with_bank[1:] != rest:
        return None
    return {'table': table, 'fallback': fallback, 'key': hit['key'], 'bank': hit['bank'], 'rest': rest,
            'value': arms[0][1], 'banked_first': hit['op'] == '!=', 'span': hit.span()}


def _strip(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _helper(first, mask):
    count = len(first['rest'])
    names = ['i', 'r'] if count == 2 else [f'i{n}' for n in range(count)]
    names.reverse()  # the innermost index comes first, as the call sites read: store(i, r, b, v)
    value = f'v & {mask}' if mask else 'v'
    banked = f'{first["table"]}[b]' + ''.join(f'[{x}]' for x in reversed(names))
    plain = first['fallback'] + ''.join(f'[{x}]' for x in reversed(names))
    arms = [f'{banked} = {value};', f'{plain} = {value};']
    if not first['banked_first']:
        arms.reverse()
    test = f'b {"!=" if first["banked_first"] else "=="} {first["key"]}'
    params = ', '.join([f'u8 {x}' for x in names] + ['u8 b', 'u8 v'])
    return (f'inline static void {HELPER}({params})\n{{\n  if ({test})\n  {{\n    {arms[0]}\n  }}\n'
            f'  else\n  {{\n    {arms[1]}\n  }}\n}}\n\n')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(rf'\b{HELPER}\b', source):
        return []
    sites = [s for s in map(_site, STATEMENT.finditer(part.clean, part.opening, part.end)) if s]
    if sites:
        key = lambda s: (s['table'], s['fallback'], s['key'], s['banked_first'], len(s['rest']))
        sites = [s for s in sites if key(s) == key(sites[0])]
    if len(sites) < MINIMUM:
        return []
    masks = [MASKED.match(s['value']) for s in sites]
    common = all(masks) and len({m['mask'] for m in masks}) == 1
    span = find(source, name)
    results = []
    for mode in ('plain', 'masked', 'shifted') if common else ('plain',):
        edits = [(span[0], span[0], _helper(sites[0], masks[0]['mask'] if mode != 'plain' else None))]
        for site, mask in zip(sites, masks):
            value = site['value']
            if mode == 'masked' or (mode == 'shifted' and '>>' in mask['value']):
                value = _strip(mask['value'])
            edits.append((*site['span'], f'{HELPER}({", ".join(list(reversed(site["rest"])) + [site["bank"], value])});'))
        text = edit(source, edits)
        if all(text != other for _, other in results):
            results.append((FAMILY, text))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
