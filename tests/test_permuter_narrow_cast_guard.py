import pytest
from pycparser import c_parser

from decomprepair.permuter_gen import protect_narrow_cast


class Rejected(Exception):
    pass


def try_cast(type_, expression):
    parser = c_parser.CParser()
    function = parser.parse(f'unsigned f(unsigned x) {{ return {expression}; }}').ext[0]

    def native(fn, *args):
        statement = parser.parse(f'unsigned f(unsigned x) {{ return ({type_})({expression}); }}')
        fn.body.block_items[0].expr = statement.ext[0].body.block_items[0].expr

    protect_narrow_cast(native, Rejected)(function, None, None, None, None)


@pytest.mark.parametrize(('type_', 'expression'), [
    ('unsigned short', '(x & 0xfff) | 0xe4000000U'),
    ('unsigned char', 'x | 0400'),
    ('short', '0x12345678U'),
])
def test_rejects_new_cast_that_discards_known_bits(type_, expression):
    with pytest.raises(Rejected):
        try_cast(type_, expression)


def test_allows_full_width_and_small_packed_literal():
    try_cast('unsigned int', 'x | 0xe4000000U')
    try_cast('unsigned short', 'x | 0x200')


def test_leaves_preexisting_casts_to_the_judge():
    fn = c_parser.CParser().parse('unsigned f(unsigned x) { return (unsigned short)(x | 0xe4000000U); }').ext[0]
    protect_narrow_cast(lambda *args: None, Rejected)(fn, None, None, None, None)
