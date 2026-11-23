from decomprepair import late_pointer_load_in_store as r

SOURCE = '''extern char *gActor;
extern volatile long *gProbe;
extern void link(long, long, long);
extern void settle(void);

void f(void)
{
  *((f32 *) (((char *) gActor) + 0x2C)) = -3.0f;
  link(*gProbe, 0, 1);
  settle();
}
'''


def children(source=SOURCE):
    return [text for fam, text in r.variants(source, 'f') if fam == 'late_pointer_load_in_store']


def test_the_pointer_is_loaded_inside_the_stores_right_hand_side():
    out = children()
    assert len(out) == 1
    assert 'volatile long *__repair_probe;' in out[0]
    assert '= (__repair_probe = gProbe, -3.0f);' in out[0]
    assert 'link(*__repair_probe, 0, 1);' in out[0]


def test_a_pointer_the_store_names_is_left_alone():
    assert children(SOURCE.replace('(((char *) gActor) + 0x2C)', '(((char *) gProbe) + 0x2C)')) == []


def test_a_call_that_reads_the_pointer_twice_or_not_through_a_deref_is_left_alone():
    assert children(SOURCE.replace('link(*gProbe, 0, 1);', 'link(*gProbe, *gProbe, 1);')) == []
    assert children(SOURCE.replace('link(*gProbe, 0, 1);', 'link((long) gProbe, 0, 1);')) == []


def test_a_store_of_a_value_that_is_not_a_literal_is_left_alone():
    assert children(SOURCE.replace('-3.0f;', 'gValue;')) == []


def test_the_pointer_must_be_a_declared_global_pointer():
    assert children(SOURCE.replace('extern volatile long *gProbe;', 'extern long gProbe;')) == []
