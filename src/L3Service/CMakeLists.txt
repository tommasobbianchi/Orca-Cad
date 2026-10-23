# TaglIAtelle L3 kernel service — standalone headless JSON-RPC 2.0 over a Unix
# socket, linking the Orca CAD kernel directly. Gated on SLIC3R_CAD (the CAD
# sources only exist in libslic3r when it is ON), which is guaranteed by the
# parent (src/CMakeLists.txt) that add_subdirectory's us inside if(SLIC3R_CAD).
#
# nanosvg_impl.cpp provides the single-header NanoSVG implementation symbols that
# NSVGUtils.o (inside libslic3r.a) references; libslic3r.a does NOT contain them
# (the GUI/tests supply them via their own NANOSVG_IMPLEMENTATION #define).
add_executable(l3_service l3_service.cpp nanosvg_impl.cpp)

# `-Wl,--start-group` / `--end-group` are placed as *link items* (not link
# options) so they wrap the whole flattened archive set. CMake inlines
# libslic3r's transitive PRIVATE deps (admesh, clipper, OCCT_LIBS,
# libslic3r_cgal, eigen, mcut, TBB, ...) between the two flags, so the linker
# rescans the group until fixpoint. This resolves the admesh ->
# Slic3r::CNumericLocalesSetter reverse dependency without whole-archive and
# without per-symbol anchors. The two header-only INTERFACE targets
# (nlohmann_json, boost_headeronly) emit no link artifact, so the effective link
# line is `-Wl,--start-group libslic3r.a admesh.a ... -Wl,--end-group`.
target_link_libraries(l3_service PRIVATE
    "-Wl,--start-group"
    libslic3r
    nlohmann_json
    boost_headeronly
    "-Wl,--end-group"
)

set_target_properties(l3_service PROPERTIES FOLDER "L3Service")
