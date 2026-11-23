"""A function-like macro used in the function, written out where it is used."""
from decomprepair import registry
from decomprepair.statement_macro_expand import FAMILY, variants

SOURCE = """#define PACK(a, b) (((a) << 8) | (b))
#define TWICE(read) x = read; y = read; ++count
#define OBJECT 4
void f(u8 *p, s32 *out)
{
  s32 x;
  s32 y;
  s32 count;
  count = 0;
  TWICE(PACK(p[0], p[1]));
  out[0] = PACK(x + OBJECT, y);
}
"""


def test_every_call_is_written_out_and_the_define_goes_when_nothing_names_it():
    (family, child), = variants(SOURCE, 'f')
    assert family == FAMILY
    assert 'x = (((p[0]) << 8) | (p[1])); y = (((p[0]) << 8) | (p[1])); ++count;' in child
    assert 'out[0] = (((x + OBJECT) << 8) | (y));' in child
    assert '#define PACK' not in child and '#define TWICE' not in child
    assert '#define OBJECT 4' in child


def test_a_macro_with_a_wrong_count_or_stringification_is_left_alone():
    assert variants(SOURCE.replace('PACK(p[0], p[1])', 'PACK(p[0])'), 'f') == []
    assert variants('#define S(a) #a\nvoid f(void)\n{\n  S(x);\n}\n', 'f') == []
    assert variants('void f(void)\n{\n  g(x);\n}\n', 'f') == []


def test_a_define_still_used_elsewhere_stays():
    source = SOURCE + 'void g(s32 *out)\n{\n  out[0] = PACK(1, 2);\n}\n'
    (_, child), = variants(source, 'f')
    assert '#define PACK' in child and '#define TWICE' not in child


def test_registry_declares_the_family():
    repair = registry.get('statement_macro_expand')
    assert repair is not None and registry.problems(repair) == [] and FAMILY in repair.families
