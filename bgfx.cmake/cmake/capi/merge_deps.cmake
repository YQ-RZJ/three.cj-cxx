# merge_deps.cmake — shaderc_capi 依赖归档合并（CI-PATCH3c）
# 用法: cmake -DDEPS="glslang,spirv-opt,spirv-cross" -DAR=<ar> -DOUTPUT=<archive>
#       -DCAPI=<archive> -DLIBDIR=<dir> -P merge_deps.cmake
# 注意: DEPS 用逗号分隔——cmd.exe 会剥引号并把分号变空格，列表传参失真（实测）
# 方案: ar MRI 脚本 CREATE/ADDLIB/SAVE 整库合并——不解包成员，彻底规避
# Windows 大小写不敏感文件系统上同名成员（glslang Pp.cpp.o vs shaderc
# pp.cpp.o）互相覆盖的问题（解包回填方案实测丢符号，SIGSEGV）。
# 注意: llvm-ar 不支持 GNU ar 的 OPEN 命令（实测 unknown command），
# 必须用 CREATE 新建输出，再 ADDLIB 逐个并入（含 capi 自身）。

# DEPS 以逗号分隔传入（cmd.exe 下分号被空格替换导致列表失真），此处还原
string(REPLACE "," ";" DEPS "${DEPS}")

set(_script "")
string(APPEND _script "CREATE ${OUTPUT}\n")
string(APPEND _script "ADDLIB ${CAPI}\n")
foreach(_dep ${DEPS})
    string(APPEND _script "ADDLIB ${LIBDIR}/lib${_dep}.a\n")
endforeach()
string(APPEND _script "SAVE\nEND\n")

set(_script_file "${OUTPUT}.mri")
file(WRITE "${_script_file}" "${_script}")

execute_process(
    COMMAND "${AR}" -M
    INPUT_FILE "${_script_file}"
    RESULT_VARIABLE _res
)
if(NOT _res EQUAL 0)
    message(FATAL_ERROR "merge_deps: ar -M failed (${_res})")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E rm -f "${_script_file}"
)
message(STATUS "merge_deps: merged ${DEPS} into ${OUTPUT}")
