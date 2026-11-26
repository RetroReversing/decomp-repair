#!/usr/bin/env python3
"""Compile the library's hot, pure modules with Cython, next to their sources (optional).

The modules in NATIVE are the ones nearly every repair family imports (the statement scanner, the C source helpers,
the MIPS readers): each trial calls them thousands of times. Cython compiles them unchanged from plain Python, so
there is one source of truth. Python's import system prefers a compiled `<name>.<abi>.so` to `<name>.py` in the same
folder, so building is all it takes, and deleting the `.so` files (`--clean`) restores the interpreted modules.

Without Cython or a C compiler nothing is built and nothing changes. `DECOMPREPAIR_NATIVE=0` has no effect at import
(the choice is which files exist), so tests run both ways by building and cleaning.

    native_build.py                    build the typed kernels (KERNELS: seconds) next to this file
    native_build.py --all              also compile every module in NATIVE unchanged (about an hour, ~3% faster)
    native_build.py --clean            remove the compiled modules
    native_build.py --only a,b         build just those modules of KERNELS and NATIVE
    native_build.py --package DIR      work on the decomprepair folder DIR (an installed copy: it must hold the
                                       .py files; needs Cython and setuptools, run it with the file's path so the
                                       package's own imports are not needed)
"""
import hashlib
import importlib.util
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent  # --package DIR builds into another copy (an installed bundle)

# Add a module here once its tests pass compiled. Keep to modules that don't read their own source or `__file__`.
# Typed code (.pyx): faster per call by a large factor, and it compiles in seconds, so a bundle build always does it.
KERNELS = ["_scan"]

# Plain modules compiled unchanged: measured about 3% on a draft pass for an hour of compiling, so only `--all` does it.
NATIVE = [
    "integer_repair_support",
    "pattern_repairs",
    "csource",
    "mips",
    "local_flow",
    "line_scan",
    "integer_abi",
    "mips_returns",
    "call_lifetime_repairs",
    "operand_lifetime_repairs",
    "large_stack_drafts",
    "compiler_phase_repairs",
    "measured_stack_drafts",
    "clamp_return_local",
    "allocator_call_guards",
    "pointer_pair_repairs",
    "c_scan",
    "m2cfix",
    "goto_structure_repairs",
    "arm_block_support",
    "target_call_arity_repairs",
    "loop_address_hoist_repairs",
    "identical_arm_collapse_repairs",
    "target_memory_repairs",
    "case_temporary_repairs",
    "branch_call_support",
    "mips_addresses",
    "shared_default_drafts",
    "stack_read_retry",
    "frame_padding_repairs",
    "equal_value_flow",
    "loaded_byte_repairs",
    "reassigned_local_inline",
    "hand_found_support",
    "permuter_macro_effects",
    "mips_regions",
    "narrow_store_repairs",
    "trig_axis_reuse",
    "balanced_clamp_predicates",
    "float_literal_global",
    "declaration_scope_sink_repairs",
    "phase_lifetime_repairs",
    "compiler_shape_repairs",
    "passthrough_argument_repairs",
    "sdk_io_repairs",
    "local_inline_repairs",
    "target_conversion_order_repairs",
    "balanced_float_predicate_return",
    "display_cursor_record_repairs",
    "float_bit_argument_repairs",
    "repair_source_view",
    "local_web_split",
    "register_repairs",
    "increment_old_value_copy",
    "mips_return_paths",
    "call_global_stage",
    "allocation_weight_combination",
    "balanced_signed_selector_increment",
    "natural_pointer_spill",
    "inferred_layout_repairs",
    "join_tail_arm_split_repairs",
    "target_constant_repairs",
    "measured_control_repairs",
    "int_global_array_read",
    "frame_slot_alias_split",
    "run_weight_scope",
    "scaffold_strip",
    "call_carrier_pointer_split",
    "local_weight_ladder",
    "stack_call_output_repairs",
    "allocation_repairs",
    "float_arm_roles",
    "quadratic_sign_holder",
    "leaf_frame_repairs",
    "if_tree_switch_repairs",
    "integer_lifetime_repairs",
    "guarded_loop_for",
    "expression_terms",
    "hoisted_invariant_inline",
    "repair_tokens",
    "unaligned_stack_drafts",
    "loop_liveness",
    "target_edge_repairs",
    "invariant_shift_local",
    "target_guard_width_repairs",
    "loop_weight_set_repairs",
    "symbols",
    "indexed_record_support",
    "extern_size_widen",
    "store_run_order",
    "wide_update_before_flags",
    "returned_register_local",
    "vector_output_capture",
    "global_pointer_run_repairs",
    "symbol_base_repairs",
    "branch_tail_distribution",
    "mips_live_return_address",
    "bit_predicate_repairs",
    "entry_parameter_copy_repairs",
    "call_weight_ladder",
    "mips_materializations",
    "ido_stack_iterators",
    "target_call_constant_repairs",
    "symbol_width_repairs",
    "field_load_repairs",
    "byte_field_macros",
    "halfword_store_repairs",
    "measured_staged_float_order",
    "inode_cache_drafts",
    "byte_increment_repairs",
    "shared_product_repairs",
    "measured_address_repairs",
    "repair_preflight",
    "early_return_guard_block",
    "saved_register_cascade",
    "narrow_chains",
    "byte_index_local",
    "measured_storage_repairs",
    "missing_call_argument_local",
    "field_struct_view_repairs",
    "hardware_operation_repairs",
    "loop_weight_repairs",
    "kmc_operand_repairs",
    "product_split_sum",
    "ido_cursor_drafts",
    "arm_argument_copy_join",
    "clamp_saved_argument_lifetime",
    "structured_loop_repairs",
    "call_result_join_copy",
    "normalization_repairs",
    "balanced_clamp_argument_stage",
    "loop_invariant_key_copy",
    "macro_scope_weight",
    "argument_mask_repairs",
    "constant_initializer_staging",
    "constant_store_scope",
    "switch_case_order_repairs",
    "balanced_selector_zero",
    "loop_counter_roles_repairs",
    "operand_focus",
    "loop_guard_counter_compare",
    "dispatch_specialization",
    "compound_operand_split",
    "lockstep_cursor_index",
    "chain_weight_scope",
    "volatile_cast_unpin",
    "paired_statement_moves",
    "branch_layout_repairs",
    "phase_projection_holders",
    "debris",
]


def compiled() -> list[Path]:
    return [p for name in KERNELS + NATIVE for p in PACKAGE.glob(f"{name}.*") if p.suffix in (".so", ".pyd")]


def clean() -> None:
    for path in compiled():
        path.unlink()
    for name in KERNELS + NATIVE:
        for stamp in PACKAGE.glob(f"{name}.*.source"):
            stamp.unlink()


def build_one(name: str, package: Path | None = None) -> int:
    """Compile one module; a module Cython can't translate stays interpreted without blocking the others."""
    from Cython.Build import cythonize
    from setuptools import Extension
    from setuptools.dist import Distribution
    package = Path(package or PACKAGE)
    source = package / f"{name}.pyx"
    if not source.is_file():
        source = package / f"{name}.py"
    # stamped on the built file so the library passes over it once the source changes (_native_guard.py)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="decomprepair-native-") as work:
        try:
            extensions = cythonize([Extension(f"decomprepair.{name}", [str(source)])],
                                   build_dir=work, quiet=True, compiler_directives={"language_level": "3"})
            dist = Distribution({"ext_modules": extensions, "package_dir": {"": "src"}, "packages": ["decomprepair"]})
            command = dist.get_command_obj("build_ext")
            command.build_lib = work
            command.build_temp = str(Path(work) / "tmp")
            command.ensure_finalized()
            command.run()
        except (Exception, SystemExit) as error:  # no C compiler or headers, or code Cython can't translate
            print(f"{name}: not built, stays interpreted ({str(error)[:200]})")
            return 0
        count = 0
        for path in Path(work).rglob("decomprepair/*"):
            if path.suffix in (".so", ".pyd"):
                (package / path.name).write_bytes(path.read_bytes())
                (package / (path.name + ".source")).write_text(digest + "\n", encoding="ascii")
                count += 1
        return count


def main(argv: list[str]) -> int:
    global PACKAGE
    if "--package" in argv:
        PACKAGE = Path(argv[argv.index("--package") + 1]).resolve()
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None  # a few modules, to try it
    wanted = KERNELS + NATIVE if "--all" in argv or only else KERNELS
    names = [name for name in wanted if only is None or name in only]
    clean()
    if "--clean" in argv:
        return 0
    if any(importlib.util.find_spec(module) is None for module in ("Cython", "setuptools")):
        print("Cython or setuptools is unavailable: the library stays interpreted.")
        return 0
    jobs = int(os.environ.get("DECOMPREPAIR_NATIVE_JOBS", "4"))
    try:
        with ProcessPoolExecutor(jobs) as pool:
            built = sum(pool.map(build_one, names, [PACKAGE] * len(names)))
    except BrokenProcessPool:  # a compiler worker was killed (memory pressure): finish what is missing one at a time
        built = len(compiled()) + sum(build_one(name, PACKAGE) for name in names if not list(PACKAGE.glob(f"{name}.*.so"))
                                      and not list(PACKAGE.glob(f"{name}.*.pyd")))
    print(f"Built {built} native modules into {PACKAGE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
