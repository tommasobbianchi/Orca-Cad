#include "DesignTextDialog.hpp"

#include "slic3r/GUI/GUI_App.hpp"
#include "slic3r/GUI/I18N.hpp"
#include "slic3r/GUI/Widgets/DialogButtons.hpp"
#include "slic3r/Utils/WxFontUtils.hpp"
#include "libslic3r/AppConfig.hpp"
#include "libslic3r/Emboss.hpp"

#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/dcbuffer.h>
#include <wx/fontenum.h>
#include <wx/graphics.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>

#include <algorithm>
#include <limits>

namespace Slic3r { namespace GUI {

static const char* kFontKey   = "cad_text_font";     // WxFontUtils::store_wxFont descriptor
static const char* kHeightKey = "cad_text_height";   // mm

DesignTextDialog::DesignTextDialog(wxWindow* parent)
    : DPIDialog(parent, wxID_ANY, _L("Text"), wxDefaultPosition, wxDefaultSize, wxDEFAULT_DIALOG_STYLE)
{
    SetFont(wxGetApp().normal_font());
    SetBackgroundColour(wxGetApp().dark_mode() ? wxColour(0x2d, 0x2d, 0x31) : *wxWHITE);
    const int em = em_unit();

    // Last used font and height, else the system GUI font at 10 mm.
    wxFont font = wxSystemSettings::GetFont(wxSYS_DEFAULT_GUI_FONT);
    double height = 10.0;
    if (AppConfig* cfg = wxGetApp().app_config) {
        const std::string desc = cfg->get(kFontKey);
        if (!desc.empty()) {
            wxFont f = WxFontUtils::load_wxFont(desc);
            if (f.IsOk()) font = f;
        }
        const std::string h = cfg->get(kHeightKey);
        if (!h.empty()) {
            try { height = std::clamp(std::stod(h), 0.5, 500.0); } catch (...) {}
        }
    }

    auto* form = new wxFlexGridSizer(2, em / 2, em);
    form->AddGrowableCol(1, 1);

    m_text = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxSize(30 * em, -1),
                            wxTE_PROCESS_ENTER);
    m_text->SetHint(_L("Type the text to insert"));
    form->Add(new wxStaticText(this, wxID_ANY, _L("Text")), 0, wxALIGN_CENTER_VERTICAL);
    form->Add(m_text, 1, wxEXPAND);

    // Scalable faces only ('@' faces are the vertical-writing aliases GTK/MSW list twice).
    wxArrayString faces = wxFontEnumerator::GetFacenames(wxFONTENCODING_SYSTEM, false);
    faces.erase(std::remove_if(faces.begin(), faces.end(), [](const wxString& f) { return f.StartsWith("@"); }),
                faces.end());
    faces.Sort();
    m_face = new wxChoice(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, faces);
    int sel = m_face->FindString(font.GetFaceName());
    m_face->SetSelection(sel != wxNOT_FOUND ? sel : 0);
    form->Add(new wxStaticText(this, wxID_ANY, _L("Font")), 0, wxALIGN_CENTER_VERTICAL);
    form->Add(m_face, 1, wxEXPAND);

    auto* style = new wxBoxSizer(wxHORIZONTAL);
    m_bold   = new wxCheckBox(this, wxID_ANY, _L("Bold"));
    m_italic = new wxCheckBox(this, wxID_ANY, _L("Italic"));
    m_bold->SetValue(WxFontUtils::is_bold(font));
    m_italic->SetValue(WxFontUtils::is_italic(font));
    style->Add(m_bold, 0, wxRIGHT, em);
    style->Add(m_italic, 0);
    form->AddSpacer(0);
    form->Add(style, 0);

    m_height = new wxSpinCtrlDouble(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxSize(10 * em, -1),
                                    wxSP_ARROW_KEYS, 0.5, 500.0, height, 0.5);
    m_height->SetDigits(1);
    form->Add(new wxStaticText(this, wxID_ANY, _L("Height (mm)")), 0, wxALIGN_CENTER_VERTICAL);
    form->Add(m_height, 0);

    // The outline of what will be inserted, fitted to the box, with its real size under it.
    m_preview = new wxWindow(this, wxID_ANY, wxDefaultPosition, wxSize(30 * em, 10 * em));
    m_preview->SetBackgroundStyle(wxBG_STYLE_PAINT);
    m_preview->Bind(wxEVT_PAINT, [this](wxPaintEvent&) { draw_preview(m_preview); });
    m_preview->Bind(wxEVT_SIZE, [this](wxSizeEvent& e) { m_preview->Refresh(); e.Skip(); });
    m_size = new wxStaticText(this, wxID_ANY, wxEmptyString);

    auto* buttons = new DialogButtons(this, {"OK", "Cancel"});
    m_ok = buttons->GetOK();

    auto* top = new wxBoxSizer(wxVERTICAL);
    top->Add(form, 0, wxEXPAND | wxALL, em);
    top->Add(m_preview, 1, wxEXPAND | wxLEFT | wxRIGHT, em);
    top->Add(m_size, 0, wxLEFT | wxRIGHT | wxTOP, em);
    top->Add(buttons, 0, wxEXPAND);

    m_text->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { update_preview(); });
    m_text->Bind(wxEVT_TEXT_ENTER, [this](wxCommandEvent&) {
        if (!m_regions.empty()) EndModal(wxID_OK);   // Enter = OK, as everywhere in the tab
    });
    auto refont = [this](wxCommandEvent&) { load_font(); update_preview(); };
    m_face->Bind(wxEVT_CHOICE, refont);
    m_bold->Bind(wxEVT_CHECKBOX, refont);
    m_italic->Bind(wxEVT_CHECKBOX, refont);
    m_height->Bind(wxEVT_SPINCTRLDOUBLE, [this](wxSpinDoubleEvent&) { update_preview(); });
    m_height->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { update_preview(); });
    Bind(wxEVT_BUTTON, [this](wxCommandEvent& e) {
        if (e.GetId() != wxID_OK) { e.Skip(); return; }
        if (m_regions.empty()) return;              // nothing to insert: the size line says why
        if (AppConfig* cfg = wxGetApp().app_config) {
            cfg->set(kFontKey, WxFontUtils::store_wxFont(current_font()));
            cfg->set(kHeightKey, std::to_string(m_height->GetValue()));
        }
        EndModal(wxID_OK);
    });

    wxGetApp().UpdateDlgDarkUI(this);
    SetSizerAndFit(top);
    CenterOnParent();

    load_font();
    update_preview();
    m_text->SetFocus();
}

wxString DesignTextDialog::text() const { return m_text->GetValue(); }

wxFont DesignTextDialog::current_font() const
{
    wxFontInfo info(12);
    if (m_face->GetSelection() != wxNOT_FOUND)
        info.FaceName(m_face->GetStringSelection());
    info.Bold(m_bold->GetValue()).Italic(m_italic->GetValue());
    return wxFont(info);
}

void DesignTextDialog::load_font()
{
    const wxFont font = current_font();
    m_font_file.reset();
    if (font.IsOk() && WxFontUtils::can_load(font))
        m_font_file = WxFontUtils::create_font_file(font);
}

void DesignTextDialog::update_preview()
{
    const std::string utf8(m_text->GetValue().ToUTF8().data());
    m_regions.clear();
    if (m_font_file && !utf8.empty())
        m_regions = text_to_regions(utf8, m_height->GetValue(), m_font_file);

    wxString line;
    if (!m_font_file)
        line = _L("This font cannot be used for text — pick another one");
    else if (utf8.empty())
        line = _L("Type the text to see its size");
    else if (m_regions.empty())
        line = _L("This font has no outline for this text");
    else {
        double lo_x = std::numeric_limits<double>::max(), lo_y = lo_x;
        double hi_x = -lo_x, hi_y = -lo_x;
        for (const auto& r : m_regions)
            for (const auto& c : r)
                for (const Vec2d& p : c) {
                    lo_x = std::min(lo_x, p.x()); hi_x = std::max(hi_x, p.x());
                    lo_y = std::min(lo_y, p.y()); hi_y = std::max(hi_y, p.y());
                }
        line = wxString::Format(_L("Size: %.1f × %.1f mm"), hi_x - lo_x, hi_y - lo_y);
    }
    m_size->SetLabel(line);
    if (m_ok) m_ok->Enable(!m_regions.empty());
    m_preview->Refresh();
}

void DesignTextDialog::draw_preview(wxWindow* canvas)
{
    wxAutoBufferedPaintDC dc(canvas);
    const bool dark = wxGetApp().dark_mode();
    dc.SetBackground(wxBrush(dark ? wxColour(0x1e, 0x1e, 0x22) : wxColour(0xf4, 0xf4, 0xf6)));
    dc.Clear();
    if (m_regions.empty()) return;

    double lo_x = std::numeric_limits<double>::max(), lo_y = lo_x, hi_x = -lo_x, hi_y = -lo_x;
    for (const auto& r : m_regions)
        for (const auto& c : r)
            for (const Vec2d& p : c) {
                lo_x = std::min(lo_x, p.x()); hi_x = std::max(hi_x, p.x());
                lo_y = std::min(lo_y, p.y()); hi_y = std::max(hi_y, p.y());
            }
    const wxSize sz  = canvas->GetClientSize();
    const double pad = 0.08 * std::min(sz.x, sz.y);
    const double w = std::max(hi_x - lo_x, 1e-6), h = std::max(hi_y - lo_y, 1e-6);
    const double k = std::min((sz.x - 2 * pad) / w, (sz.y - 2 * pad) / h);
    const double ox = 0.5 * (sz.x - k * w), oy = 0.5 * (sz.y + k * h);   // y up -> screen y down

    std::unique_ptr<wxGraphicsContext> gc(wxGraphicsContext::Create(dc));
    if (!gc) return;
    wxGraphicsPath path = gc->CreatePath();
    for (const auto& r : m_regions)
        for (const auto& c : r) {
            if (c.empty()) continue;
            path.MoveToPoint(ox + k * (c[0].x() - lo_x), oy - k * (c[0].y() - lo_y));
            for (size_t i = 1; i < c.size(); ++i)
                path.AddLineToPoint(ox + k * (c[i].x() - lo_x), oy - k * (c[i].y() - lo_y));
            path.CloseSubpath();
        }
    gc->SetBrush(wxBrush(wxColour(0x00, 0x96, 0x88)));   // Orca accent
    gc->SetPen(*wxTRANSPARENT_PEN);
    gc->FillPath(path, wxODDEVEN_RULE);                    // holes (the counter of an "o") stay open
}

void DesignTextDialog::on_dpi_changed(const wxRect&)
{
    Fit();
    Refresh();
}

}} // namespace Slic3r::GUI
