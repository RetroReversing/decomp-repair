"""integer_abi.scalar was a fifth of a live Deep Permuter run: it blanked and searched the whole header for every local of
every family. It now keeps the blanked header and its answers; it must answer exactly as before."""
import importlib.util
import itertools
import pathlib
import random
import sys

from decomprepair import csource, integer_abi

REFERENCE = pathlib.Path(__file__).with_name('integer_abi_reference.py')


def _reference():
    spec = importlib.util.spec_from_file_location('decomprepair.integer_abi_reference', REFERENCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SPELLINGS = ['int', 'unsigned int', 'u8', 'u16', 's32', 'u32', 'char', 'unsigned char', 'short', 'long', 'long long',
             'Handle', 'Mode', 'Ptr', 'Pair', 'Loop', 'Flags', 'const int', 'volatile u8', 'float', 'unknown_t', '']
LINES = ['typedef unsigned char u8;', 'typedef signed short s16;', 'typedef unsigned short u16;', 'typedef int s32;',
         'typedef unsigned int u32;', 'typedef u8 Handle;', 'typedef u16 Mode;', 'typedef Handle Alias;',
         'typedef int (*Ptr)(int);', 'typedef int Pair[2];', 'typedef Loop Flags;', 'typedef Flags Loop;',
         '#define Mode int', '#define Ptr char', '/* typedef char Flags; */', '"typedef long Mode;"', 'typedef u8 Mode;',
         'typedef struct { int x; } Pair2;', '// #define Handle long']


def test_cached_answers_equal_the_original_on_random_headers():
    reference = _reference()
    rng = random.Random(3)
    for _ in range(300):
        context = '\n'.join(rng.sample(LINES, rng.randint(0, 9)))
        for arch, spelling in itertools.product(['mips', 'x86', None, 'z80'], rng.sample(SPELLINGS, 8)):
            assert integer_abi.scalar(spelling, context, arch) == reference.scalar(spelling, context, arch), (context, spelling, arch)
            assert integer_abi.scalar(spelling, context, arch) == reference.scalar(spelling, context, arch)  # and again, cached


def test_a_changed_header_is_not_answered_from_another_headers_cache():
    assert integer_abi.scalar('Handle', 'typedef unsigned char Handle;', 'mips') == (8, False)
    assert integer_abi.scalar('Handle', 'typedef short Handle;', 'mips') == (16, True)
    assert integer_abi.scalar('Handle', '#define Handle int', 'mips') is None
    assert integer_abi.scalar('Handle', 'typedef unsigned char Handle;', 'mips') == (8, False)


def test_only_a_few_headers_are_kept():
    for index in range(integer_abi.CONTEXTS * 3):
        integer_abi.scalar('Handle', f'typedef int Handle; /* {index} */', 'mips')
    assert len(integer_abi._contexts) <= integer_abi.CONTEXTS


def test_alternating_between_a_header_and_a_source_no_longer_blanks_each_time():
    csource._blank.cache_clear()
    header, source = 'typedef int a;' * 50, 'int f(void) { return 1; }' * 50
    for _ in range(5):
        csource._blank(header)
        csource._blank(source)
    info = csource._blank.cache_info()
    assert (info.misses, info.hits) == (2, 8)
