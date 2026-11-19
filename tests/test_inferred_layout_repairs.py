from decomprepair import inferred_layout_repairs as repair


def test_consistent_repeated_accesses_make_a_candidate_local_record():
    source = 'void f(void *p) { *(int*)((char*)p+20) = 1; use(*((int *) (((char *) p) + 20))); *(short*)((char*)p+24) = 2; }'
    variants = repair.variants(source, 'f', 'mips')
    assert len(variants) == 1
    text = variants[0][1]
    assert 'unsigned char pad_0[20]; int field_14; short field_18;' in text
    assert text.count('((__repair_record_p*)p)->field_14') == 2
    assert 'void f(void *p)' in text
    assert 'typedef struct' in text


def test_conflicting_overlapping_misaligned_or_dynamic_layouts_are_rejected():
    source = 'void f(void *p) { use(*(int*)((char*)p+20)); use(*(int*)((char*)p+20)); use(*(short*)((char*)p+24)); }'
    for invalid in (source.replace('short', 'char').replace('p+24','p+21'),
                    source.replace('p+24','p+25'), source.replace('p+24','p+offset'),
                    source.replace('*(short*)','*(double*)'), source.replace('void *p','volatile void *p')):
        assert not repair.variants(invalid, 'f', 'mips')
    assert not repair.variants(source, 'f', 'mips64')
    assert not repair.variants(source.replace('p+20', 'p+24'), 'f', 'mips')


def test_comments_strings_and_other_functions_are_not_inferred():
    source = 'void g(void *p) { use(*(int*)((char*)p+20)); use(*(int*)((char*)p+20)); use(*(int*)((char*)p+24)); }\nvoid f(void) { puts("*(int*)((char*)p+24)"); }'
    assert not repair.variants(source, 'f', 'mips')


def test_initialized_local_byte_pointer_offsets_use_record_views():
    source = 'void f(void) { u8 *p = global; use(*((u16 *)(p + 30))); use(*((u16 *)(p + 14))); use(*((u16 *)(p + 14))); }'
    variants = repair.variants(source, 'f', 'mips')
    assert len(variants) == 1
    text = variants[0][1]
    assert 'u8 *p = global;' in text
    assert 'unsigned char pad_0[14]; unsigned short field_E;' in text
    assert text.count('((__repair_record_p*)p)->field_E') == 2
    assert 'unsigned short field_1E;' in text


def test_implicit_offsets_require_an_unescaped_unique_byte_pointer():
    source = 'void f(void) { u8 *p = global; use(*((u16 *)(p + 30))); use(*((u16 *)(p + 14))); use(*((u16 *)(p + 14))); }'
    for extra in ('p = other;', 'p++;', 'escape(p);', 'escape(&p);', 'u8 *alias = p;',
                  '{u8 *p = other;}', 'use(p[0]);', 'use(*((u32 *)(p + 14)));'):
        assert not repair.variants(source.replace(' }', extra + ' }'), 'f', 'mips')
    for before in ('#define global other\n', '#if ENABLED\n'):
        assert not repair.variants(before + source, 'f', 'mips')
    for typ in ('u16', 'void', 'volatile u8', 'const u8'):
        assert not repair.variants(source.replace('u8 *p', typ + ' *p'), 'f', 'mips')


def test_implicit_byte_forms_and_supported_architectures():
    source = 'void f(void) { u8 *p = global; use(*((u16 *)(p + 30))); use(*((u16 *)(p + 14))); use(*((u16 *)(p + 14))); }'
    for typ in ('char', 's8', 'unsigned char', 'signed char'):
        for arch in ('mips', 'ppc', 'x86', 'arm', 'thumb'):
            assert repair.variants(source.replace('u8 *p', typ + ' *p'), 'f', arch)
    for invalid in (source.replace('void f(void) { u8 *p = global;', 'void f(u8 *p) {'),
                    source.replace('u8 *p = global;', 'u8 *p = global, *other;'),
                    source.replace('p + 30', 'p + offset')):
        assert not repair.variants(invalid, 'f', 'mips')


def test_m2c_field_macros_form_a_record():
    # m2c writes every field access as M2C_FIELD: an N64 function needed `temp_a0` as a record (gcc 2.7.2 lets a
    # global's load pass a store through a struct member, not through a cast pointer).
    from decomprepair import inferred_layout_repairs as layouts
    source = '''void f(void *temp_a0, u8 x) {
    if (M2C_FIELD(temp_a0, u16 *, 2) == 0) {
        M2C_FIELD(temp_a0, u16 *, 2) = 1U;
        M2C_FIELD(temp_a0, u8 *, 1) = 0xFF;
        M2C_FIELD(temp_a0, u8 *, 0) = x;
    }
}
'''
    (family, out), = layouts.variants(source, 'f', 'mips')
    assert family == 'inferred_record_layout'
    assert ('typedef struct { unsigned char field_0; unsigned char field_1; unsigned short field_2; } '
            '__repair_record_temp_a0;') in out
    assert '((__repair_record_temp_a0*)temp_a0)->field_2 = 1U;' in out and 'M2C_FIELD' not in out
    # overlapping fields stay as they are
    assert layouts.variants(source.replace('M2C_FIELD(temp_a0, u8 *, 1)', 'M2C_FIELD(temp_a0, s32 *, 0)'), 'f', 'mips') == []


def test_pointer_fields_and_two_stores_make_a_record():
    # A list node's links, `void **` and `void ***`: as members, gcc 2.7.2 let a global's load pass the stores
    # (an N64 function at 94.7%, exact); and a record stored only twice (another at 96.4%, exact).
    links = '''void f(void *arg0) {
    void *a;
    void **b;

    a = M2C_FIELD(arg0, void **, 0);
    b = M2C_FIELD(arg0, void ***, 4);
    M2C_FIELD(arg0, void **, 0) = NULL;
    M2C_FIELD(arg0, void ***, 4) = NULL;
    D -= 1;
}
'''
    (_, out), = repair.variants(links, 'f', 'mips')
    assert 'void * field_0; void * field_4;' in out and '((__repair_record_arg0*)arg0)->field_4 = NULL;' in out
    twice = '''void f(void *p, s32 a, s16 b) {
    M2C_FIELD(p, s32 *, 0) = a;
    M2C_FIELD(p, s16 *, 4) = b;
    g(*D);
}
'''
    assert repair.variants(twice, 'f', 'mips')


def test_parenthesised_and_integer_cast_bases():
    source = '''void f(void *p) {
    (*(s16 *)((char *)(p) + 0x78)) = 1;
    (*(s16 *)((char *)(p) + 0x7A)) = 0;
    (*(s32 *)((char *)((s32)p) + 0x5C)) = 2;
}
'''
    (_, out), = repair.variants(source, 'f', 'mips')
    assert out.count('((__repair_record_p*)p)->') == 3
