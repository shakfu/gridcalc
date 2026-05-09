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
