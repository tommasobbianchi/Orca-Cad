#pragma once

#include <functional>
#include <string>
#include <vector>

#include "libslic3r/CAD/Quotes.hpp"

namespace Slic3r {

namespace GUI {

class Camera;
class ImGuiWrapper;

// One issue of the print check, pinned on the part: a dot where it is, a numbered note beside it.
struct PrintNote
{
    Vec3d       at{Vec3d::Zero()};   // model frame
    std::string kind;
    std::string text;
    int         n{0};
    bool        warning{false};      // a warning (amber) or a suggestion (blue)
    bool        open{true};          // false once the user dismissed it
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

    void render(ImGuiWrapper& imgui, const Camera& camera);
    bool hovered() const { return m_hovered; }

private:
    bool m_hovered{false};
};

} // namespace GUI
} // namespace Slic3r
