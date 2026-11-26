"""Rules learnt from matches: the one change between C that missed and C that matched, as a declarative rule (rules.py).

The change is widened to whole statements, and its names and numbers become slots, so `return *(s32 *)D_1000;` made
volatile proposes the same on any such load. Only a change the rule can reproduce on the C it came from is kept, and
what writes new names or numbers is refused: a rule can only rearrange what the other function already has. A rule is a
hypothesis like any repair; the caller decides how many independent matches make one worth keeping.
"""
import difflib
import hashlib
import re

from . import rules
from .integer_repair_support import view

TOKEN = re.compile(r'''"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|//[^\n]*|/\*[\s\S]*?\*/|0[xX][0-9a-fA-F]+[uUlL]*'''
                   r'''|\d+(?:\.\d*)?[fFuUlL]*|[A-Za-z_]\w*|->|<<=|>>=|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^]=|\S''')
TYPES = frozenset('void float double char short int long signed unsigned s8 s16 s32 s64 u8 u16 u32 u64 f32 f64'.split())
KEYWORDS = TYPES | frozenset(
    'return if else for while do switch case default break continue goto sizeof typedef struct union enum const '
    'volatile static extern register auto inline'.split())
BOUNDARIES = frozenset(';{}')
FILLER = frozenset(';{}(),')   # punctuation that says nothing about which statement this is
NEW_LITERALS = frozenset(('0', '1'))
MERGE_GAP = 4        # edits this many unchanged tokens apart are one change
MAX_TOKENS = 40
MAX_CHILDREN_EACH = 4
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?)[uUlLfF]*'
SLOT = re.compile(r'[$#](\d+)\Z')


def _tokens(text):
    return [token for token in TOKEN.findall(text) if not token.startswith(('//', '/*'))]


def _parts(source, name):
    """(the tokens before the body, the body's tokens) of the function, or None when rules can't rewrite it."""
    part = view(source, name)
    if not part:
        return None
    return _tokens(source[:part.opening + 1]), _tokens(source[part.opening + 1:part.end - 1])


def _change(left, right):
    """The one changed span of two token lists widened to whole statements, as (old, new); None for no or several."""
    spans = []
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        if spans and a0 - spans[-1][1] <= MERGE_GAP:
            spans[-1][1], spans[-1][3] = a1, b1
        else:
            spans.append([a0, a1, b0, b1])
    if len(spans) != 1:
        return None
    a0, a1, b0, b1 = spans[0]
    # Back to just after the previous `;`, `{` or `}`; forward through the next `;` or `}`. The tokens crossed are
    # equal on both sides, so both spans grow by the same amount.
    back = a0 - max((i + 1 for i, token in enumerate(left[:a0]) if token in BOUNDARIES), default=0)
    a0, b0 = a0 - back, max(0, b0 - back)
    if not (a1 > a0 and left[a1 - 1] in ';}'):
        forward = next((i + 1 for i, token in enumerate(left[a1:]) if token in BOUNDARIES), len(left) - a1)
        a1, b1 = a1 + forward, b1 + forward
    return left[a0:a1], right[b0:b1]


def _encode(tokens, slots, add):
    """`tokens` with names as `$n` and numbers as `#n`; None when `add` is false and a token needs a slot of its own."""
    out = []
    for token in tokens:
        number = token[0].isdigit()
        if number or (re.match(r'[A-Za-z_]', token) and token not in KEYWORDS):
            if token not in slots:
                if not add:
                    if token in NEW_LITERALS:
                        out.append(token)
                        continue
                    return None
                slots[token] = f'{"#" if number else "$"}{len(slots)}'
            out.append(slots[token])
        else:
            out.append(token)
    return out


def rewrite(before, after, name):
    """(old, new) of the change that turned `before` into `after`, each a space-joined pattern with slots; None when
    the change is not one small statement-level edit a rule can make again."""
    first, second = _parts(before, name), _parts(after, name)
    if not first or not second or first[0] != second[0]:   # a changed signature or declaration outside the body
        return None
    change = _change(first[1], second[1])
    if not change:
        return None
    old, new = change
    if not old or not new or max(len(old), len(new)) > MAX_TOKENS or old == new:
        return None
    if any(token.startswith(('"', "'", '#')) for token in old + new):
        return None
    slots = {}
    encoded = _encode(old, slots, add=True)
    written = _encode(new, slots, add=False)
    if written is None:
        return None
    # `$0 = $1 ;` says nothing about where it applies: ask for a type, or two tokens that are more than punctuation.
    fixed = [token for token in encoded if not SLOT.match(token) and token not in FILLER]
    if len(fixed) < 2 and not TYPES.intersection(fixed):
        return None
    result = ' '.join(encoded), ' '.join(written)
    made = rules.apply(rules.compile_rule(rule(*result)), before, name)
    if not any(_parts(source, name) == second for _, source in made):
        return None
    return result


def identifier(old, new):
    return 'mined_' + hashlib.sha256(f'{old}\0{new}'.encode()).hexdigest()[:12]


def _pattern(tokens):
    seen, out, word_before = set(), [], False
    for token in tokens:
        slot = SLOT.match(token)
        word = bool(slot) or bool(re.match(r'\w', token))
        if out:
            out.append(r'\s+' if word and word_before else r'\s*')
        if slot:
            group = f's{slot[1]}'
            if group in seen:
                out.append(rf'\b(?P={group})\b')
            else:
                seen.add(group)
                body = NUMBER if token.startswith('#') else r'[A-Za-z_]\w*'
                out.append(rf'\b(?P<{group}>{body})\b')
        else:
            out.append(rf'\b{token}\b' if word else re.escape(token))
        word_before = word
    return ''.join(out)


def rule(old, new, archs=(), description=''):
    """The declarative rule (rules.py) for a `rewrite` result: every site, and one child per site."""
    key = identifier(old, new)
    template = ' '.join('{s%s}' % slot[1] if (slot := SLOT.match(token)) else token for token in new.split())
    out = {
        'schema': rules.SCHEMA, 'id': key, 'families': [key, key + '_one'],
        'sites': [{'match': r'(?P<lead>(?:[;{}]|^)\s*)' + _pattern(old.split()), 'replace': '{lead}' + template}],
        'children': {'all': key, 'each': {'family': key + '_one', 'when_sites_over': 1, 'max': MAX_CHILDREN_EACH}},
    }
    if description:
        out['description'] = description
    known = [arch for arch in archs if arch in rules.ARCHS]
    if known:
        out['archs'] = known
    return out
