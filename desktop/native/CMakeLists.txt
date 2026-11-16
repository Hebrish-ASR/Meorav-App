# libmeorav.so (Linux x86_64) / meorav.dll (Windows x64, MSVC): qwentts.cpp (Qwen3-TTS on ggml, CPU backend) + the flat C API in
# meorav_c.cpp, loaded by the Python app with ctypes. Mirrors android/app/src/main/cpp/CMakeLists.txt.
#
#   cmake -S desktop/native -B build -DMEORAV_X86_LEVEL=v3 && cmake --build build -j
#
# MEORAV_X86_LEVEL picks the instruction set, because ggml is static and GGML_NATIVE is off:
#   v3   AVX2 + FMA + F16C (Intel Haswell 2013+, AMD Zen 2017+): the fast build
#   v2   SSE4.2 only: the fallback for older CPUs; the app picks it when /proc/cpuinfo lacks avx2
# A v3 build on a CPU without AVX2 dies with SIGILL (Windows: illegal instruction), so the
# package ships both.
#
# Windows (since 0.2.0): MSVC, static CRT (/MT), so meorav.dll needs only system DLLs:
#   cmake -S desktop/native -B build/v3 -A x64 -DMEORAV_X86_LEVEL=v3 && cmake --build build/v3 --config Release
cmake_minimum_required(VERSION 3.22)
project(meorav_desktop C CXX)
if(MSVC)
    # Static CRT: no VC++ redistributable needed next to meorav.dll.
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    # qwentts sources carry non-ASCII literals and use fopen & co (same flags as its own CMake).
    add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
    add_compile_options($<$<COMPILE_LANGUAGE:C,CXX>:/utf-8>)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()
set(MEORAV_X86_LEVEL "v3" CACHE STRING "v3 (AVX2) or v2 (SSE4.2)")

set(QT_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/qwentts.cpp)

# Must be set before ggml is added: tokenizer tensor names exceed ggml's default of 64.
add_compile_definitions(GGML_MAX_NAME=128)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(GGML_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(GGML_CCACHE OFF CACHE BOOL "" FORCE)
if(MEORAV_X86_LEVEL STREQUAL "v3")
    set(GGML_SSE42 ON CACHE BOOL "" FORCE)
    set(GGML_AVX ON CACHE BOOL "" FORCE)
    set(GGML_AVX2 ON CACHE BOOL "" FORCE)
    set(GGML_FMA ON CACHE BOOL "" FORCE)
    set(GGML_F16C ON CACHE BOOL "" FORCE)
    set(GGML_BMI2 ON CACHE BOOL "" FORCE)
elseif(MEORAV_X86_LEVEL STREQUAL "v2")
    set(GGML_SSE42 ON CACHE BOOL "" FORCE)
    set(GGML_AVX OFF CACHE BOOL "" FORCE)
    set(GGML_AVX2 OFF CACHE BOOL "" FORCE)
    set(GGML_FMA OFF CACHE BOOL "" FORCE)
    set(GGML_F16C OFF CACHE BOOL "" FORCE)
    set(GGML_BMI2 OFF CACHE BOOL "" FORCE)
else()
    message(FATAL_ERROR "MEORAV_X86_LEVEL must be v3 or v2")
endif()
set(GGML_AVX512 OFF CACHE BOOL "" FORCE)
set(GGML_AVX_VNNI OFF CACHE BOOL "" FORCE)
add_subdirectory(${QT_DIR}/ggml ggml)

# version.h is normally generated from `git rev-parse`; keep in step with the submodule pin
# (same string as the Android build).
set(QT_GEN ${CMAKE_CURRENT_BINARY_DIR}/qt-gen)
file(WRITE ${QT_GEN}/version.h "#pragma once\n#define QWEN_VERSION \"5916bf7 (2026-10-16)\"\n")

add_library(qwen-core STATIC
    ${QT_DIR}/src/qwen.cpp
    ${QT_DIR}/src/pipeline-tts.cpp
    ${QT_DIR}/src/pipeline-codec.cpp
)
target_compile_definitions(qwen-core PUBLIC QWEN_STATIC)
target_include_directories(qwen-core PUBLIC ${QT_DIR}/src ${QT_DIR} ${QT_GEN})
target_include_directories(qwen-core SYSTEM PUBLIC ${QT_DIR}/ggml/include)
target_link_libraries(qwen-core PUBLIC ggml)

find_package(Threads REQUIRED)
add_library(meorav SHARED meorav_c.cpp)
set_target_properties(meorav PROPERTIES CXX_VISIBILITY_PRESET hidden C_VISIBILITY_PRESET hidden)
target_link_libraries(meorav PRIVATE qwen-core Threads::Threads)
if(NOT MSVC)
    # Static libstdc++/libgcc: the .so then needs only glibc, whatever the system's GCC.
    target_link_options(meorav PRIVATE -static-libstdc++ -static-libgcc -Wl,--exclude-libs,ALL)
endif()
