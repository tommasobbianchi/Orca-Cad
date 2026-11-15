#pragma once

#include <functional>
#include <string>
#include <vector>

#include "libslic3r/CAD/Quotes.hpp"

struct indexed_triangle_set;   // global: the index-triangle mesh the red tint reads

namespace Slic3r {

class AABBMesh;

namespace GUI {

class Camera;
class ImGuiWrapper;

// One issue of the print check, pinned on the part: a dot where it is, a numbered note beside it.
struct PrintNote
{
    Vec3d       at{Vec3d::Zero()};   // model frame
    std::string kind;
    std::string text;
    std::string fix_label;   // label of the auto-fix button ("" = no automatic fix)
    std::string fix_json;    // JSON {"steps":[...]} for the fix; empty = none
    int         n{0};
    bool        warning{false};      // a warning (amber) or a suggestion (blue)
    bool        open{true};          // false once the user dismissed it
    bool        has_pin{true};       // false = a global note (orientation / tight_pair): no pin, no tint
    Vec3d       normal{Vec3d::Zero()};
    bool        has_normal{false};
    std::vector<int> tris;           // triangle indices into the body's display mesh (red tint)
    bool        resolved{false};     // view state only: the note turns grey, stays listed
    bool        visible{true};       // culled on the far side / occluded this frame
    mutable int tinted_tris{0};      // triangles actually tinted last frame (0 when dismissed/hidden)
};

// The dimensions of the body in the viewport, drawn the way a drawing office draws them: thin extension lines, a dimension line
// with filled arrowheads and the number set in a break of it, a diameter with its leader, a radius pointing at its arc. It owns
// no document state: the owner hands it the quotes to draw, and a click on one that has a driving feature only EMITS it.
class DesignQuoteOverlay
{
public:
    std::function<const std::vector<Quotes::Quote>&()> quotes;   // what to draw this frame
    std::function<void(int feature)>                   edit;     // a quote with a driving feature was clicked

    void render(ImGuiWrapper& imgui, const Camera& camera, float scale);
    bool hovered() const { return m_hovered; }

private:
    bool m_hovered{false};
};

// The print-check issues drawn on the object, the way ScanRuler pins its notes: a dot on the surface, a leader, a numbered note. Clicking
// a note dismisses it. Owns no state: the owner hands it the notes.
class DesignPrintNotesOverlay
{
public:
    std::function<std::vector<PrintNote>&()> notes;
    std::function<void(int)>                 dismiss;
    std::function<void(int)>                 resolve;   // toggle the grey resolved state
    std::function<void(int)>                 focus;     // focus a pin (a ring around it); the camera does not move
    std::function<void(int)>                 apply_fix; // run the note's automatic fix (Fix button)

    // Set by the canvas each frame: the body's display mesh for the red tint and the occlusion ray cast, and the focus ring.
    const indexed_triangle_set* its{nullptr};
    const AABBMesh*            aabb{nullptr};
    int  focus_index{-1};
    bool focus_active{false};

    void render(ImGuiWrapper& imgui, const Camera& camera);
    bool hovered() const { return m_hovered; }

private:
    bool m_hovered{false};
};

} // namespace GUI
} // namespace Slic3r
