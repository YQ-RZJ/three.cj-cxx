# 注意：版本范围需与 CMake 4.x 兼容 —— 交叉编译 toolchain（ohos.toolchain.cmake）
# 对 CMAKE_C_COMPILER 的普通 set 是否生效取决于 policy 版本；range 语法（如 SDL3
# 工程）可让 CMake 4 正确启用新 toolchain 机制，避免误用宿主编译器（MSVC cl.exe）。
cmake_minimum_required(VERSION 3.16...4.4)

project(dlbridge C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# 动态库加载桥：通用、纯 C、无第三方依赖。
# 动态库是主要形态（dlopen 桥必须为 .so/.dll/.dylib）；--libtype static 时也可出静态库。
option(DLBRIDGE_SHARED "构建 dlbridge 动态库" ON)
if(DLBRIDGE_SHARED)
    add_library(dlbridge SHARED src/dlbridge.c)
else()
    add_library(dlbridge STATIC src/dlbridge.c)
endif()

# 构建 DLL 时导出 dlb_* 符号（Windows 必须 dllexport，见 include/dlbridge.h）
target_compile_definitions(dlbridge PRIVATE DLBRIDGE_BUILD=1)

target_include_directories(dlbridge PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

# POSIX (OpenHarmony/Linux/Android/macOS)：链接 libdl
if(UNIX)
    target_link_libraries(dlbridge PRIVATE ${CMAKE_DL_LIBS})
endif()

if(MSVC)
    # /utf-8：源文件为 UTF-8（含中文注释），否则 MSVC 按本机代码页(936)解析会导致
    # 注释边界错乱、C2061/C4819 等诡异语法错误
    target_compile_options(dlbridge PRIVATE /utf-8 /W3)
else()
    target_compile_options(dlbridge PRIVATE -Wall -Wextra)
endif()

# 安装规则：库到 lib/、头文件到 include/（供 build.py stage 打包 + libs/ 复制）
install(TARGETS dlbridge
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
        RUNTIME DESTINATION bin)
install(FILES include/dlbridge.h DESTINATION include)
