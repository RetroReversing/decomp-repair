"""Resolve conservative scalar widths for the app's supported 32-bit repair targets."""
import re
import threading
from collections import OrderedDict

from .csource import _blank

ARCHES = {'mips', 'ppc', 'x86', 'arm', 'thumb'}


CONTEXTS = 8  # header texts whose blanked copy and answers are kept (the last few functions' worth)
_contexts: OrderedDict = OrderedDict()
_lock = threading.Lock()


def _entry(context):
    """(the context with comments and strings blanked, the answers found in it so far). Blanking the header and
    searching it for typedefs and defines was a fifth of a live Deep Permuter run (one scan per local per family),
    and csource._blank keeps only the last text, so alternating with the source redid it every call."""
    with _lock:
        held = _contexts.get(context)
        if held is not None:
            _contexts.move_to_end(context)
            return held
    held = (_blank(context), {})
    with _lock:
        _contexts[context] = held
        while len(_contexts) > CONTEXTS:
            _contexts.popitem(last=False)
    return held


def scalar(spelling, context='', arch=None, seen=()):
    """Return (bits, signed), or None for unknown, conflicting or qualified declarations.

    Never use the host Python/C ABI: these architecture adapters describe 32-bit targets.
    Unknown architectures and preprocessor-defined aliases do not establish a width.
    """
    if arch not in ARCHES:
        return None
    spelling = ' '.join(spelling.split())
    if not spelling or spelling in seen or len(seen) > 8 or re.search(r'\b(?:volatile|const|_Atomic)\b',spelling):
        return None
    clean, answers = _entry(context)
    key = (spelling, arch, tuple(seen))
    if key in answers:
        return answers[key]
    answers[key] = result = _scalar(spelling, context, arch, seen, clean)
    return result


def _scalar(spelling, context, arch, seen, clean):
    if re.search(r'(?m)^\s*#\s*define\s+'+re.escape(spelling)+r'\b',clean):
        return None
    if re.search(r'\btypedef[^;{}]*(?:\(\s*\*\s*'+re.escape(spelling)+r'\b|\b'+re.escape(spelling)+r'\s*\[)',clean):
        return None
    definitions = re.findall(r'\btypedef\s+([^;{}]+?)\b'+re.escape(spelling)+r'\s*;',clean)
    if definitions:
        types = [scalar(t,context,arch,seen+(spelling,)) for t in definitions]
        return types[0] if types[0] is not None and all(t==types[0] for t in types) else None
    words = spelling.split()
    unsigned = 'unsigned' in words
    words = [w for w in words if w not in {'signed','unsigned','int'}]
    if words == ['char']:
        return (8,not unsigned) if spelling != 'char' else None
    if words == ['short']:
        return 16,not unsigned
    if words in ([],['long']):
        return 32,not unsigned
    if words == ['long','long']:
        return 64,not unsigned
    return None
