// ============================================================================
// RequireCJLibNAPI.h — requireCJLib 的 OHOS NAPI 接口声明
//
// 用途：为 requireCJLib 工具库提供 ArkTS 调用接口，编译为 .a 后链接到
//       仓颉 .so 产物中，ArkTS 侧通过 import 即可调用。
//
// ArkTS 侧使用示例：
//   import requireCJLib from 'requireCJLib';
//
//   // ---- 运行时生命周期 ----
//   requireCJLib.initRuntime();
//   requireCJLib.loadLibraryWithInit("libmylib");
//
//   // ---- 参数传递链路：ArkTS → C/C++ → 仓颉 ----
//   // 1. 分配原生 buffer 用于存放参数
//   const buf = requireCJLib.allocBuffer(24);          // 24 bytes
//   // 2. 按仓颉 @C struct 内存布局写入各字段
//   requireCJLib.writeInt64(buf, 0, BigInt(100));      // offset 0: Int64
//   requireCJLib.writeFloat64(buf, 8, 3.14);           // offset 8: Float64
//   requireCJLib.writeBool(buf, 16, true);             // offset 16: Bool
//   // 3. 查找仓颉函数并调用（buf 即参数地址）
//   const fnPtr = requireCJLib.findSymbol("libmylib", "myFunc");
//   const ret = requireCJLib.runTaskAndAwait(fnPtr, buf);
//   // 4. 读取返回值（若仓颉函数返回结构体/基本类型）
//   const retVal = requireCJLib.readInt64(ret, 0);
//   // 5. 释放 buffer
//   requireCJLib.freeBuffer(buf);
//
//   // ---- 清理 ----
//   requireCJLib.unloadLibrary("libmylib");
//   requireCJLib.finiRuntime();
//
// 注册方法列表（ArkTS 侧方法名）：
//   [运行时生命周期]
//   initRuntime()                        — 初始化仓颉运行时
//   finiRuntime()                        — 结束仓颉运行时
//   isRuntimeInitialized()               — 查询运行时是否已初始化
//
//   [动态库管理]
//   loadLibrary(libName)                 — 仅加载动态库
//   initLibrary(libName)                 — 仅初始化动态库
//   loadLibraryWithInit(libName)         — 加载 + 初始化
//   unloadLibrary(libName)               — 卸载动态库
//   findSymbol(libName, symbolName)      — 查找导出符号，返回 bigint
//
//   [任务执行]
//   runTask(funcPtr, argsPtr)            — 异步执行，返回 bigint（句柄）
//   getTaskRet(handle)                   — 阻塞获取结果
//   getTaskRetWithTimeout(handle, timeoutMs) — 带超时获取结果
//   releaseHandle(handle)                — 释放任务句柄
//   runTaskAndAwait(funcPtr, argsPtr, timeoutMs?) — 同步执行并获取结果
//
//   [Buffer 管理 — 打通 ArkTS → C/C++ → 仓颉 参数传递链路]
//   allocBuffer(size)                    — 分配原生内存，返回 bigint（地址）
//   freeBuffer(ptr)                      — 释放原生内存
//   memsetBuffer(ptr, value, size)       — 清零/填充内存
//
//   [Buffer 写入 — 按仓颉 CType 类型映射写入]
//   writeBool(ptr, offset, value)        — 写入 Bool (1 byte)
//   writeInt8(ptr, offset, value)        — 写入 Int8
//   writeUInt8(ptr, offset, value)       — 写入 UInt8
//   writeInt16(ptr, offset, value)       — 写入 Int16
//   writeUInt16(ptr, offset, value)      — 写入 UInt16
//   writeInt32(ptr, offset, value)       — 写入 Int32
//   writeUInt32(ptr, offset, value)      — 写入 UInt32
//   writeInt64(ptr, offset, value)       — 写入 Int64（bigint）
//   writeUInt64(ptr, offset, value)      — 写入 UInt64（bigint）
//   writeFloat32(ptr, offset, value)     — 写入 Float32
//   writeFloat64(ptr, offset, value)     — 写入 Float64
//   writePointer(ptr, offset, value)     — 写入指针地址（bigint）
//   writeString(ptr, offset, str)        — 写入 UTF-8 字符串（含 null 终止符）
//   writeBytes(ptr, offset, arraybuffer) — 写入原始字节（ArrayBuffer）
//
//   [Buffer 读取 — 按仓颉 CType 类型映射读取]
//   readBool(ptr, offset)                — 读取 Bool → boolean
//   readInt8(ptr, offset)                — 读取 Int8 → number
//   readUInt8(ptr, offset)               — 读取 UInt8 → number
//   readInt16(ptr, offset)               — 读取 Int16 → number
//   readUInt16(ptr, offset)              — 读取 UInt16 → number
//   readInt32(ptr, offset)               — 读取 Int32 → number
//   readUInt32(ptr, offset)              — 读取 UInt32 → number
//   readInt64(ptr, offset)               — 读取 Int64 → bigint
//   readUInt64(ptr, offset)              — 读取 UInt64 → bigint
//   readFloat32(ptr, offset)             — 读取 Float32 → number
//   readFloat64(ptr, offset)             — 读取 Float64 → number
//   readPointer(ptr, offset)             — 读取指针地址 → bigint
//   readString(ptr, offset)              — 读取 null 终止字符串 → string
//   readBytes(ptr, offset, length)       — 读取原始字节 → ArrayBuffer
//
// 类型映射对照（仓颉 CType ↔ NAPI Buffer API）：
//   | 仓颉类型   | C 类型     | 字节数 | NAPI 写入方法        | NAPI 读取方法       |
//   |-----------|-----------|-------|---------------------|--------------------|
//   | Bool      | bool      | 1     | writeBool           | readBool           |
//   | UInt8     | uint8_t   | 1     | writeUInt8          | readUInt8          |
//   | Int8      | int8_t    | 1     | writeInt8           | readInt8           |
//   | Int16     | int16_t   | 2     | writeInt16          | readInt16          |
//   | UInt16    | uint16_t  | 2     | writeUInt16         | readUInt16         |
//   | Int32     | int32_t   | 4     | writeInt32          | readInt32          |
//   | UInt32    | uint32_t  | 4     | writeUInt32         | readUInt32         |
//   | Int64     | int64_t   | 8     | writeInt64(bigint)  | readInt64→bigint   |
//   | UInt64    | uint64_t  | 8     | writeUInt64(bigint) | readUInt64→bigint  |
//   | Float32   | float     | 4     | writeFloat32        | readFloat32        |
//   | Float64   | double    | 8     | writeFloat64        | readFloat64        |
//   | CString   | char*     | 8/ptr | writeString         | readString         |
//   | CPointer  | void*     | 8/ptr | writePointer(bigint)| readPointer→bigint |
//   | @C struct | struct    | varies| 逐字段 write*       | 逐字段 read*       |
//
// NDK 位置：C:\Program Files\HuaWei\DevEco Studio\sdk\default\openharmony\native
// ============================================================================
#pragma once

#include "node_api.h"

namespace requirecj_napi {

// NAPI 模块初始化入口：注册所有方法到 exports 对象。
// 由 napi_module 的 nm_register_func 回调调用。
napi_value Init(napi_env env, napi_value exports);

}  // namespace requirecj_napi
