# requireCJLib-ark NAPI 变体 — CMake 构建文件
#
# 编译产物：librequirecj_napi.a / librequirecj_napi.so
# 包含：RequireCJLib.cpp（仓颉运行时 C API 封装）+ RequireCJLibNAPI.cpp（OHOS NAPI 注册层）
# 用途：编译为 .a 后链接到仓颉 .so 产物中，ArkTS 侧通过 import 'requireCJLib' 调用
#
# 需要 OHOS NDK 的 node_api.h 头文件：
#   <OHOS_NDK>/sysroot/usr/include/node_api.h
cmake_minimum_required(VERSION 3.16...4.4)

project(requirecj_napi CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# 库类型：REQUIRECJ_NAPI_SHARED=ON 出动态库，OFF 出静态库（默认静态）
option(REQUIRECJ_NAPI_SHARED "构建 requirecj_napi 动态库（默认 OFF = 静态库）" OFF)

set(NAPI_SOURCES
    src/RequireCJLib.cpp
    src/RequireCJLibNAPI.cpp
)

if(REQUIRECJ_NAPI_SHARED)
    add_library(requirecj_napi SHARED ${NAPI_SOURCES})
else()
    add_library(requirecj_napi STATIC ${NAPI_SOURCES})
endif()

target_include_directories(requirecj_napi PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

# OHOS NDK node_api.h 头文件路径
# 当使用 ohos.toolchain.cmake 时 sysroot 已自动包含；
# 手动交叉编译时需确保 OHOS_NDK/sysroot/usr/include 在搜索路径中
if(DEFINED OHOS_NDK)
    target_include_directories(requirecj_napi PRIVATE
        ${OHOS_NDK}/sysroot/usr/include
    )
endif()

# POSIX：链接 libdl
if(UNIX)
    target_link_libraries(requirecj_napi PRIVATE ${CMAKE_DL_LIBS})
endif()

if(MSVC)
    target_compile_options(requirecj_napi PRIVATE /utf-8 /W3)
else()
    target_compile_options(requirecj_napi PRIVATE -Wall -Wextra)
endif()

# 动态库构建时，仓颉运行时符号（InitCJRuntime 等）在编译期不可用，
# 它们由仓颉 .so 在运行时提供，需要告诉链接器允许未解析符号
if(REQUIRECJ_NAPI_SHARED)
    if(CJ_RUNTIME_LIB_DIR)
        # 链接仓颉运行时库以解析符号
        target_link_directories(requirecj_napi PRIVATE ${CJ_RUNTIME_LIB_DIR})
        target_link_libraries(requirecj_napi PRIVATE cangjie-runtime cangjie-trace)
    else()
        # 未指定仓颉运行时库路径，允许未解析符号
        if(MSVC)
            target_link_options(requirecj_napi PRIVATE /FORCE:UNRESOLVED)
        elseif(APPLE)
            target_link_options(requirecj_napi PRIVATE -undefined dynamic_lookup)
        else()
            # GCC/Clang: 允许未解析符号（Linux/Android/OHOS）
            # CI-PATCH: OHOS 工具链（ohos.toolchain.cmake）默认追加
            # -Wl,--no-undefined，--allow-shlib-undefined 是独立开关抵消
            # 不了它——napi_*（宿主 libace_napi.z.so 运行时提供）与
            # 仓颉运行时符号（InitCJRuntime 等）链接期全部报 undefined
            # （OHOS job 实测）。--unresolved-symbols=ignore-all 与
            # requireCJLib（ffi 侧）Android 修复同款，lld 认可。
            target_link_options(requirecj_napi PRIVATE
                -Wl,--allow-shlib-undefined
                -Wl,--unresolved-symbols=ignore-all)
        endif()
    endif()
endif()

# 安装规则
install(TARGETS requirecj_napi
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
        RUNTIME DESTINATION bin)
install(FILES
    include/requireCJLib/RequireCJLib.h
    include/requireCJLib/RequireCJLibNAPI.h
    DESTINATION include/requireCJLib)
