"""A global scalar passed to a call that follows another call: its address taken before the first call.

m2c writes `v = first(x); second(0, gG, v, ...);` and the compiled order is the one the scheduler gives it: the second call's
argument moves (`move $a2,$v0`) go ahead of the load of `gG`. The target loads it after the first call's result move, with the
address's `lui` above the first call: the game read the global through a pointer it had set up before the call. The
rewrite names that pointer:

    v = first(x);                                { s32 *addr = &gG;
    second(0, gG, v, 1);                 ->        v = first(x);
                                                   second(0, *addr, v, 1); }

(the `lui` of `gG` is then a pseudo of its own, born before the call, and the load keeps its place behind the call). Found by
hand on a state machine's caption call: 60 -> 0, the last two rows (docs/learnings/function/identical-run-goto-state-machine-arms.md);
four spellings that kept the read as the plain global (a result local, the call nested in the argument, a block-local
result, the value read before the first call) left the order alone or moved the load above the first call.

`gG` must be declared `extern T gG;` with a scalar `T` in the source or the shared header. Hypothesis: the order follows
sched.c's priorities, which the address pseudo changes by shortening the chain behind the load.
"""
import re

from .csource import _blank, find

FAMILY = 'global_argument_address_stage'
FAMILIES = (FAMILY,)

LIMIT = 6
_RESULT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<var>[A-Za-z_]\w*)[ \t]*=[ \t]*[A-Za-z_]\w*\([^\n;]*\);[ \t]*\n')
_CALL = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<callee>[A-Za-z_]\w*)\((?P<args>[^\n;]*)\);[ \t]*\n')
_LOCAL = 'global_address'


def _scalar(source, header, name):
    for text in (source, header or ''):
        m = re.search(r'\bextern\s+(?P<type>[A-Za-z_][\w\s]*?)\s+' + re.escape(name) + r'\s*;', _blank(text))
        if m and '*' not in m['type']:
            return ' '.join(m['type'].split())
    return None


def variants(source, name, header=None):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0 or re.search(r'\b' + _LOCAL + r'\b', clean[span[0]:span[1]]):
        return []
    result = []
    for first in _RESULT.finditer(clean, opening + 1, span[1]):
        second = _CALL.match(clean, first.end())
        if not second or second['callee'] in ('if', 'while', 'for', 'switch', 'return'):
            continue
        if not re.search(r'\b' + re.escape(first['var']) + r'\b', second['args']):
            continue
        for glob in dict.fromkeys(re.findall(r'(?<![\w.>&*])([A-Za-z_]\w*)(?![\w(\[])', second['args'])):
            kind = _scalar(source, header, glob)
            if not kind or glob == first['var']:
                continue
            args = re.sub(r'(?<![\w.>&*])' + re.escape(glob) + r'(?![\w(\[])', '*' + _LOCAL, second['args'])
            indent = first['indent']
            call = f'{indent}{second["callee"]}({args});\n'
            text = (source[:first.start()] + f'{indent}{{\n{indent}{kind} *{_LOCAL} = &{glob};\n' +
                    source[first.start():second.start()] + call + f'{indent}}}\n' + source[second.end():])
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
