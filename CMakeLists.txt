cmake_minimum_required(VERSION 3.15...3.31)
project(${SKBUILD_PROJECT_NAME} VERSION ${SKBUILD_PROJECT_VERSION} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
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
nanobind_add_module(_core src/gridcalc/_core.cpp)

target_link_libraries(_core PRIVATE OpenXLSX::OpenXLSX)

if(MSVC)
    target_compile_options(_core PRIVATE /W4)
else()
    target_compile_options(_core PRIVATE -Wall -Wextra)
endif()

install(TARGETS _core DESTINATION gridcalc)
