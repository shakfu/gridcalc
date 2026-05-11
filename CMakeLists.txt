cmake_minimum_required(VERSION 3.15...3.31)
project(${SKBUILD_PROJECT_NAME} VERSION ${SKBUILD_PROJECT_VERSION} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# `Development.SABIModule` is required for nanobind's STABLE_ABI mode
# (the target `Python::SABIModule` must exist; nanobind silently
# downgrades STABLE_ABI to OFF when it's missing). Marked optional
# rather than required so non-cpython interpreters or older Python
# installations still configure cleanly -- the abi3 path simply won't
# be available in that case.
find_package(Python REQUIRED COMPONENTS Interpreter Development.Module
                    OPTIONAL_COMPONENTS Development.SABIModule)
find_package(nanobind CONFIG REQUIRED)

# --- OpenXLSX ---------------------------------------------------------------
# Disable parts of OpenXLSX we don't need when consumed as a subdirectory.
set(OPENXLSX_CREATE_DOCS    OFF CACHE BOOL "" FORCE)
set(OPENXLSX_BUILD_SAMPLES  OFF CACHE BOOL "" FORCE)
set(OPENXLSX_BUILD_TESTS    OFF CACHE BOOL "" FORCE)
set(OPENXLSX_BUILD_BENCHMARKS OFF CACHE BOOL "" FORCE)
set(BUILD_SHARED_LIBS       OFF CACHE BOOL "" FORCE)
# miniz / older fetched deps still declare cmake_minimum_required(VERSION < 3.5);
# CMake 4 removed that compat. Restore the floor for fetched subprojects.
set(CMAKE_POLICY_VERSION_MINIMUM "3.5" CACHE STRING "" FORCE)
add_subdirectory(thirdparty/OpenXLSX EXCLUDE_FROM_ALL)

# --- lp_solve + _opt extension ----------------------------------------------
# Vendors lp_solve 5.5 as a static archive and exposes a minimal LP solver
# entry point through the `_opt` nanobind module. The static lib stays
# EXCLUDE_FROM_ALL; only `_opt` is installed into the wheel, and the linker
# pulls in just the LP/MIP code paths it actually references.
option(GRIDCALC_BUILD_OPT "Build the _opt extension (lp_solve-backed LP solver)" ON)
if(GRIDCALC_BUILD_OPT)
    add_subdirectory(thirdparty/lp_solve_5.5 EXCLUDE_FROM_ALL)

    if(GRIDCALC_STABLE_ABI)
        nanobind_add_module(_opt STABLE_ABI src/gridcalc/_opt.cpp)
    else()
        nanobind_add_module(_opt src/gridcalc/_opt.cpp)
    endif()

    target_link_libraries(_opt PRIVATE lpsolve_static)

    if(MSVC)
        target_compile_options(_opt PRIVATE /W4)
    else()
        target_compile_options(_opt PRIVATE -Wall -Wextra)
        target_link_options(_opt PRIVATE
            $<$<PLATFORM_ID:Darwin>:-Wl,-dead_strip>
            $<$<PLATFORM_ID:Linux>:-Wl,--gc-sections>)
    endif()

    install(TARGETS _opt DESTINATION gridcalc)
endif()

# --- _core extension --------------------------------------------------------
# `GRIDCALC_STABLE_ABI=ON` builds a single wheel that targets nanobind's
# stable ABI (PEP 384). Such wheels carry the `cp312-abi3` tag and install
# unchanged on Python 3.12+. Off by default so per-version development
# builds and the existing wheel matrix continue to behave the same.
option(GRIDCALC_STABLE_ABI "Build _core with nanobind's stable ABI (Python>=3.12)" OFF)

if(GRIDCALC_STABLE_ABI)
    message(STATUS "gridcalc: building _core with STABLE_ABI (cp312-abi3)")
    nanobind_add_module(_core STABLE_ABI src/gridcalc/_core.cpp)
else()
    nanobind_add_module(_core src/gridcalc/_core.cpp)
endif()

target_link_libraries(_core PRIVATE OpenXLSX::OpenXLSX)

if(MSVC)
    target_compile_options(_core PRIVATE /W4)
else()
    target_compile_options(_core PRIVATE -Wall -Wextra)
endif()

install(TARGETS _core DESTINATION gridcalc)
