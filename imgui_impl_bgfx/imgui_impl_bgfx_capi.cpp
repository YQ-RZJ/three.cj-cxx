/**
 * @file imgui_impl_bgfx_capi.cpp
 * @brief C-linkage wrapper for the CherryGrove imgui_impl_bgfx renderer backend.
 *
 * The bgfx backend is header-only C++; this translation unit exposes a small
 * C surface so that Cangjie FFI can initialise / shutdown / render without
 * touching C++ symbols or the InitConfig struct directly.
 */

#include "imgui.h"
#include "imgui_impl_bgfx.hpp"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Initialise the bgfx renderer backend.
 * @param auto_shader       non-zero → use the embedded shader/sampler.
 * @param starting_view_id  first bgfx view id reserved for ImGui (usually 1).
 * @param max_views         maximum number of view ids to reserve.
 * @return 1 on success, 0 on failure.
 */
int imgui_cj_impl_bgfx_init(int auto_shader, int starting_view_id, int max_views) {
    CGIMBGFX::InitConfig cfg;
    cfg.autoShaderSampler = (auto_shader != 0);
    cfg.startingViewId = static_cast<bgfx::ViewId>(starting_view_id);
    cfg.maxViews = static_cast<CGIMBGFX::u16>(max_views);
    cfg.enableMultiViewport = false;
    return CGIMBGFX::ImGui_Implbgfx_Init(cfg) ? 1 : 0;
}

/**
 * @brief Shutdown the bgfx renderer backend.
 */
void imgui_cj_impl_bgfx_shutdown(void) {
    CGIMBGFX::ImGui_Implbgfx_Shutdown();
}

/**
 * @brief Render the current ImGui draw data via bgfx.
 */
void imgui_cj_impl_bgfx_render_draw_data(void) {
    ImDrawData* draw_data = ImGui::GetDrawData();
    if (draw_data != nullptr) {
        CGIMBGFX::ImGui_Implbgfx_RenderDrawData(draw_data);
    }
}

#ifdef __cplusplus
}
#endif
