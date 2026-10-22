# libmeorav.so: qwentts.cpp (Qwen3-TTS on ggml, CPU backend) + a JNI wrapper, one shared library.
#
# qwentts.cpp's own top-level CMakeLists is NOT used: it builds tools, a server, httplib and
# yyjson, and it resolves include dirs from CMAKE_SOURCE_DIR, which breaks under
# add_subdirectory. This file builds the same three sources as its `qwen-core` target.
cmake_minimum_required(VERSION 3.22.1)
project(meorav C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(QT_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../third_party/qwentts.cpp)

# Must be set before ggml is added: tokenizer tensor names exceed ggml's default of 64.
add_compile_definitions(GGML_MAX_NAME=128)

# ggml: static, CPU only. armv8.2-a+dotprod+fp16 runs on every arm64 phone core since
# ~2018 (Cortex-A55/A75 and later). i8mm (Dimensity 9000 has it) is left out on purpose: a
# binary built with it dies with SIGILL on cores without it, and TTS decode is matrix-vector
# work where i8mm adds little. No OpenMP: ggml's own thread pool, no libomp.so to ship.
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_CPU_ARM_ARCH "armv8.2-a+dotprod+fp16" CACHE STRING "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(GGML_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(GGML_CCACHE OFF CACHE BOOL "" FORCE)
add_subdirectory(${QT_DIR}/ggml ggml)

# version.h is normally generated from `git rev-parse` by tools/version.cmake; the submodule
# pin is fixed, so write it here (keep in step with the submodule commit).
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

add_library(meorav SHARED meorav_jni.cpp)
target_link_libraries(meorav PRIVATE qwen-core log)
# 16 KB page alignment (required by Google Play for targetSdk 35+ devices with 16 KB pages).
target_link_options(meorav PRIVATE "-Wl,-z,max-page-size=16384")
