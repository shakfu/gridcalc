# Static lp_solve library. Source list mirrors lpsolve55/ccc (the canonical
# upstream build script). Only the LP/MIP core is compiled; the CLI binary,
# shared library variant, demo programs, and language bindings are excluded.

# lp_solve is plain C; the top-level project declares only CXX.
enable_language(C)

set(LPSOLVE_SOURCES
    lp_MDO.c
    shared/commonlib.c
    shared/mmio.c
    shared/myblas.c
    ini.c
    fortify.c
    colamd/colamd.c
    lp_rlp.c
    lp_crash.c
    bfp/bfp_LUSOL/lp_LUSOL.c
    bfp/bfp_LUSOL/LUSOL/lusol.c
    lp_Hash.c
    lp_lib.c
    lp_wlp.c
    lp_matrix.c
    lp_mipbb.c
    lp_MPS.c
    lp_params.c
    lp_presolve.c
    lp_price.c
    lp_pricePSE.c
    lp_report.c
    lp_scale.c
    lp_simplex.c
    lp_SOS.c
    lp_utils.c
    yacc_read.c
)

add_library(lpsolve_static STATIC ${LPSOLVE_SOURCES})
set_target_properties(lpsolve_static PROPERTIES POSITION_INDEPENDENT_CODE ON)

target_include_directories(lpsolve_static PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/shared
    ${CMAKE_CURRENT_SOURCE_DIR}/colamd
    ${CMAKE_CURRENT_SOURCE_DIR}/bfp
    ${CMAKE_CURRENT_SOURCE_DIR}/bfp/bfp_LUSOL
    ${CMAKE_CURRENT_SOURCE_DIR}/bfp/bfp_LUSOL/LUSOL
)

# Standard lp_solve compile-time defines (mirrors lpsolve55/ccc).
target_compile_definitions(lpsolve_static PRIVATE
    YY_NEVER_INTERACTIVE
    PARSER_LP
    RoleIsExternalInvEngine
    INVERSE_ACTIVE=INVERSE_LUSOL
    LoadableBlasLib=0
    LoadInverseLib=0
    LoadLanguageLib=0
)

# lp_solve's source predates modern -Wall hygiene; suppress its warnings in
# this target only so the project's own warnings remain visible. -w is
# accepted by both gcc and clang.
if(NOT MSVC)
    target_compile_options(lpsolve_static PRIVATE -w)
endif()
