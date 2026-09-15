# requireCJLib C FFI 变体 — CMake 构建文件
#
# 编译产物：librequirecj_ffi.a / librequirecj_ffi.so
# 包含：RequireCJLib.cpp（仓颉运行时 C API 封装）+ RequireCJLibFFI.cpp（C FFI 桥接层）
# 用途：编译为 .a 后链接到仓颉 .so 产物中，外部通过 dlopen + C 符号调用
cmake_minimum_required(VERSION 3.16...4.4)

project(requirecj_ffi CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# 库类型：REQUIRECJ_FFI_SHARED=ON 出动态库，OFF 出静态库（默认静态）
option(REQUIRECJ_FFI_SHARED "构建 requirecj_ffi 动态库（默认 OFF = 静态库）" OFF)

set(FFI_SOURCES
    src/RequireCJLib.cpp
    src/RequireCJLibFFI.cpp
)

if(REQUIRECJ_FFI_SHARED)
    add_library(requirecj_ffi SHARED ${FFI_SOURCES})
else()
    add_library(requirecj_ffi STATIC ${FFI_SOURCES})
endif()

target_include_directories(requirecj_ffi PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

# POSIX：链接 libdl（dlopen/dlsym）
if(UNIX)
    target_link_libraries(requirecj_ffi PRIVATE ${CMAKE_DL_LIBS})
endif()

if(MSVC)
    target_compile_options(requirecj_ffi PRIVATE /utf-8 /W3)
else()
    target_compile_options(requirecj_ffi PRIVATE -Wall -Wextra)
endif()

# 动态库构建时，仓颉运行时符号（InitCJRuntime 等）在编译期不可用，
# 它们由仓颉 .so 在运行时提供，需要告诉链接器允许未解析符号
if(REQUIRECJ_FFI_SHARED)
    if(CJ_RUNTIME_LIB_DIR)
        # 链接仓颉运行时库以解析符号
        if(MSVC OR MINGW)
            # Windows: 链接 libcangjie-runtime.dll.a 和 libcangjie-trace.dll.a
            target_link_directories(requirecj_ffi PRIVATE ${CJ_RUNTIME_LIB_DIR})
            target_link_libraries(requirecj_ffi PRIVATE cangjie-runtime cangjie-trace)
        else()
            # Linux/Android/OHOS: 链接 libcangjie-runtime.so 和 libcangjie-trace.so
            target_link_directories(requirecj_ffi PRIVATE ${CJ_RUNTIME_LIB_DIR})
            target_link_libraries(requirecj_ffi PRIVATE cangjie-runtime cangjie-trace)
        endif()
    else()
        # CI-PATCH: 未指定运行时库路径时的分平台处理。PE 目标（Windows）
        # 不允许未解析符号：MinGW 的 GNU ld PE 后端不支持 ELF 专属的
        # --unresolved-symbols=ignore-all（windows job 实测 undefined
        # reference），MSVC /FORCE:UNRESOLVED 产物 "image may not run"
        # （LNK4088）。正规解法是导入桩：dlltool/lib.exe 按 .def 生成
        # 空导入库（导入表项指向 libcangjie-runtime.dll），链接期挂上
        # 即产生正确的导入表，加载期由宿主侧运行时 DLL 解析。非 Windows
        # 保持 allow-shlib-undefined / ignore-all（ELF/Mach-O 语义）。
        if(MSVC OR MINGW OR WIN32)
            set(_STUB_DEF "${CMAKE_CURRENT_SOURCE_DIR}/cangjie-runtime-stub.def")
            set(_STUB_LIB "${CMAKE_CURRENT_BINARY_DIR}/cangjie-runtime-stub.lib")
            if(MSVC)
                add_custom_command(OUTPUT "${_STUB_LIB}"
                    COMMAND lib /def:"${_STUB_DEF}" /machine:X64
                            /out:"${_STUB_LIB}" /nologo
                    DEPENDS "${_STUB_DEF}"
                    COMMENT "lib.exe: 生成仓颉运行时导入桩 ${_STUB_LIB}")
            else()
                # MinGW: dlltool 从 .def 生成导入库（-l 输出即 .dll.a 形态）
                find_program(DLLTOOL_EXE dlltool)
                if(NOT DLLTOOL_EXE)
                    message(FATAL_ERROR "MinGW 构建需要 dlltool（binutils）生成仓颉运行时导入桩")
                endif()
                add_custom_command(OUTPUT "${_STUB_LIB}"
                    COMMAND "${DLLTOOL_EXE}" --def "${_STUB_DEF}"
                            --output-lib "${_STUB_LIB}"
                    DEPENDS "${_STUB_DEF}"
                    COMMENT "dlltool: 生成仓颉运行时导入桩 ${_STUB_LIB}")
            endif()
            add_custom_target(cangjie_runtime_stub DEPENDS "${_STUB_LIB}")
            add_dependencies(requirecj_ffi cangjie_runtime_stub)
            target_link_libraries(requirecj_ffi PRIVATE "${_STUB_LIB}")
        elseif(APPLE)
            target_link_options(requirecj_ffi PRIVATE -undefined dynamic_lookup)
        else()
            # GCC/Clang (ELF): 允许未解析符号（Linux/Android/OHOS）。
            # CI-PATCH: Android NDK 工具链默认追加 -Wl,--no-undefined，而
            # --allow-shlib-undefined 是另一个独立开关，抵消不了它——
            # InitCJRuntime 等由仓颉运行时 .so 在运行时提供的符号会在
            # 链接期报 undefined。--unresolved-symbols=ignore-all（lld
            # 与 GNU ld 均支持）才能压制对象文件自身的未解析符号。
            target_link_options(requirecj_ffi PRIVATE
                -Wl,--allow-shlib-undefined
                -Wl,--unresolved-symbols=ignore-all)
        endif()
    endif()
endif()

# 安装规则
install(TARGETS requirecj_ffi
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
        RUNTIME DESTINATION bin)
install(FILES
    include/requireCJLib/RequireCJLib.h
    include/requireCJLib/RequireCJLibFFI.h
    DESTINATION include/requireCJLib)
