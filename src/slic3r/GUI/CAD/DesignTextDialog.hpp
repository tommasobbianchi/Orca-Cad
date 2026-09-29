#ifndef slic3r_GUI_DesignTextDialog_hpp_
#define slic3r_GUI_DesignTextDialog_hpp_

#include "slic3r/GUI/GUI_Utils.hpp"
#include "libslic3r/CAD/SketchImport.hpp"

#include <wx/font.h>

#include <memory>

class wxTextCtrl;
class wxChoice;
class wxCheckBox;
class wxSpinCtrlDouble;
class wxStaticText;

namespace Slic3r {
namespace Emboss { struct FontFile; }
namespace GUI {

// Text for the Design tab: the words, the font (face, bold, italic) and the height, with a
// live outline of exactly what will be inserted and its size in millimetres. The outline IS
// the result — the same vectorisation the sketch receives — so there is nothing to guess.
// Enter inserts, Esc cancels (charter 4.2). The last font and height are remembered.
class DesignTextDialog : public DPIDialog
{
public:
    explicit DesignTextDialog(wxWindow* parent);

    // The vectorised text, centred on the origin, in mm. Empty unless the dialog ended wxID_OK.
    const ImportRegions& regions() const { return m_regions; }
    wxString             text() const;

protected:
    void on_dpi_changed(const wxRect& suggested_rect) override;

private:
    void     load_font();          // m_face/m_bold/m_italic -> m_font_file
    void     update_preview();     // text/font/height -> m_regions + size label
    wxFont   current_font() const;
    void     draw_preview(wxWindow* canvas);

    wxTextCtrl*       m_text{nullptr};
    wxChoice*         m_face{nullptr};
    wxCheckBox*       m_bold{nullptr};
    wxCheckBox*       m_italic{nullptr};
    wxSpinCtrlDouble* m_height{nullptr};
    wxWindow*         m_preview{nullptr};
    wxStaticText*     m_size{nullptr};
    wxWindow*         m_ok{nullptr};

    std::shared_ptr<const Emboss::FontFile> m_font_file;
    ImportRegions                           m_regions;
};

} // namespace GUI
} // namespace Slic3r

#endif // slic3r_GUI_DesignTextDialog_hpp_
