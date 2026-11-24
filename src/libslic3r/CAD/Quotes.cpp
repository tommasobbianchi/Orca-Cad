#include "Quotes.hpp"
#include "CadDocument.hpp"

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepTools.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Tool.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <BRepBndLib.hxx>
#include <BRepGProp_Face.hxx>
#include <Bnd_Box.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Ax1.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstddef>
#include <string>
#include <utility>
#include <vector>

namespace Slic3r { namespace Quotes {

namespace {

constexpr double kPi = 3.14159265358979323846;

Vec3d to_vec(const gp_Pnt& p) { return {p.X(), p.Y(), p.Z()}; }
Vec3d to_vec(const gp_Dir& d) { return {d.X(), d.Y(), d.Z()}; }

// One cylindrical face, before faces that are halves of one cylinder are put back together.
struct Piece {
    double radius;
    bool   concave;     // the material is outside the cylinder: a bore, a hole
    double span;        // radians of the circle this face covers
    Spot   spot;
};

bool same_cylinder(const Piece& a, const Piece& b)
{
    if (a.concave != b.concave || std::abs(a.radius - b.radius) > 1e-6) return false;
    if (std::abs(std::abs(a.spot.axis.dot(b.spot.axis)) - 1.0) > 1e-6) return false;
    // the same line, and the same stretch of it
    const Vec3d d = b.spot.c0 - a.spot.c0;
    if ((d - a.spot.axis * d.dot(a.spot.axis)).norm() > 1e-4) return false;
    auto along = [&](const Vec3d& p) { return (p - a.spot.c0).dot(a.spot.axis); };
    double b0 = along(b.spot.c0), b1 = along(b.spot.c1);
    if (b0 > b1) std::swap(b0, b1);
    const double a1 = (a.spot.c1 - a.spot.c0).dot(a.spot.axis);
    return std::abs(b0) < 1e-4 && std::abs(b1 - a1) < 1e-4;
}

bool cylinder_piece(const TopoDS_Face& face, Piece& out)
{
    BRepAdaptor_Surface s(face);
    if (s.GetType() != GeomAbs_Cylinder) return false;
    const gp_Cylinder cyl = s.Cylinder();
    const double      u0 = s.FirstUParameter(), u1 = s.LastUParameter();
    const double      v0 = s.FirstVParameter(), v1 = s.LastVParameter();
    if (!(v1 - v0 > 1e-6) || !(u1 - u0 > 1e-6)) return false;
    const double um = 0.5 * (u0 + u1), vm = 0.5 * (v0 + v1);

    // Which side the material is on: the face normal (flipped with the face's orientation) points at the axis for a bore.
    gp_Pnt mid;
    gp_Vec nrm;
    BRepGProp_Face(face).Normal(um, vm, mid, nrm);
    const gp_Pnt  loc  = cyl.Location();
    const gp_Dir  dir  = cyl.Axis().Direction();
    const gp_Vec  rel(loc, mid);
    const gp_Vec  radial = rel - gp_Vec(dir) * rel.Dot(gp_Vec(dir));
    out.radius  = cyl.Radius();
    out.concave = nrm.Dot(radial) < 0.0;
    out.span    = u1 - u0;
    const Vec3d axis = to_vec(dir), origin = to_vec(loc);
    out.spot.axis = axis;
    out.spot.c0   = origin + axis * v0;
    out.spot.c1   = origin + axis * v1;
    out.spot.m0   = to_vec(s.Value(um, v0));
    out.spot.m1   = to_vec(s.Value(um, v1));
    return true;
}

// A hexagonal pocket or boss: a planar face whose outline (a hexagon, or a hexagon with a slot cut out of one side) has three
// consecutive equal straight edges meeting at 60 degrees. Quoted once per distinct size: the side of the hexagon, and the depth
// read off the wall that stands on that side.
void hexagon_quotes(const TopoDS_Shape& body, int body_index, std::vector<Quote>& out)
{
    TopTools_IndexedDataMapOfShapeListOfShape e2f;
    TopExp::MapShapesAndAncestors(body, TopAbs_EDGE, TopAbs_FACE, e2f);
    size_t added = 0;
    for (TopExp_Explorer ex(body, TopAbs_FACE); ex.More() && added < 16; ex.Next()) {
        const TopoDS_Face face = TopoDS::Face(ex.Current());
        BRepAdaptor_Surface s(face);
        if (s.GetType() != GeomAbs_Plane) continue;
        std::vector<Vec3d>       P;
        std::vector<TopoDS_Edge> E;
        bool straight = true;
        for (BRepTools_WireExplorer we(BRepTools::OuterWire(face), face); we.More(); we.Next()) {
            BRepAdaptor_Curve c(we.Current());
            if (c.GetType() != GeomAbs_Line) { straight = false; break; }
            P.push_back(to_vec(BRep_Tool::Pnt(we.CurrentVertex())));
            E.push_back(we.Current());
        }
        const size_t n = P.size();
        if (!straight || n < 6 || n > 12) continue;
        auto edge = [&](size_t i) { return P[(i + 1) % n] - P[i]; };
        auto turn = [&](size_t i) {
            const Vec3d a = edge(i).normalized(), b = edge((i + 1) % n).normalized();
            return std::acos(std::max(-1.0, std::min(1.0, a.dot(b)))) * 180.0 / kPi;
        };
        for (size_t i = 0; i < n; ++i) {
            const size_t j = (i + 1) % n, k = (i + 2) % n;
            const double L = edge(i).norm();
            if (L < 0.2 || std::abs(edge(j).norm() - L) > 1e-3 || std::abs(edge(k).norm() - L) > 1e-3) continue;
            if (std::abs(turn(i) - 60.0) > 1.0 || std::abs(turn(j) - 60.0) > 1.0) continue;
            // edge j is a side of the hexagon
            const bool seen = std::any_of(out.begin(), out.end(), [&](const Quote& q) { return q.kind == Kind::Linear && q.tag == "side" && std::abs(q.value - L) < 1e-4; });
            if (seen) break;
            const Vec3d fn  = to_vec(s.Plane().Axis().Direction());
            const Vec3d mid = 0.5 * (P[j] + P[k]);
            Vec3d centre = Vec3d::Zero();
            for (const Vec3d& p : P) centre += p;
            centre /= double(n);
            Vec3d in = centre - mid;
            in -= fn * in.dot(fn);
            if (in.norm() < 1e-9) break;
            in.normalize();
            Quote side;
            side.kind = Kind::Linear; side.tag = "side"; side.value = L; side.body = body_index;
            side.a = P[j]; side.b = P[k]; side.out = in; side.off = 0.2 * L;
            out.push_back(side);
            ++added;
            // the wall that stands on that edge gives the depth
            TopoDS_Face wall;
            bool have = false;
            for (const TopoDS_Shape& f : e2f.FindFromKey(E[j]))
                if (!have && !f.IsSame(face)) { wall = TopoDS::Face(f); have = true; }
            if (have) {
                double lo = 1e300, hi = -1e300;
                for (TopExp_Explorer ve(wall, TopAbs_VERTEX); ve.More(); ve.Next()) {
                    const double c = (to_vec(BRep_Tool::Pnt(TopoDS::Vertex(ve.Current()))) - mid).dot(fn);
                    lo = std::min(lo, c); hi = std::max(hi, c);
                }
                const double far = std::abs(lo) > std::abs(hi) ? lo : hi;   // the end away from the floor
                if (std::abs(far) > 0.05) {
                    Quote depth;
                    depth.kind = Kind::Linear; depth.tag = "depth"; depth.value = std::abs(far); depth.body = body_index;
                    depth.a = mid; depth.b = mid + fn * far; depth.out = in; depth.off = 0.2 * L;
                    out.push_back(depth);
                }
            }
            break;
        }
    }
}

} // namespace

std::string format_mm(double v)
{
    char buf[48];
    std::snprintf(buf, sizeof buf, "%.2f", v);
    std::string s = buf;
    // snprintf writes the decimal separator of the current locale: a comma under Italian. Strip the zeros after either.
    if (s.find_first_of(".,") != std::string::npos) {
        while (s.back() == '0') s.pop_back();
        if (s.back() == '.' || s.back() == ',') s.pop_back();
    }
    return s == "-0" ? "0" : s;
}

std::string Quote::text() const
{
    switch (kind) {
    case Kind::Extent:   return format_mm(value);
    case Kind::Diameter: return (count() > 1 ? std::to_string(count()) + "\xC3\x97 " : std::string()) + "\xC3\x98" + format_mm(2.0 * value);
    case Kind::Radius:   return (count() > 1 ? std::to_string(count()) + "\xC3\x97 " : std::string()) + "R" + format_mm(value);
    case Kind::Linear:   return tag + " " + format_mm(value);
    }
    return {};
}

std::vector<Quote> compute(const TopoDS_Shape& body, int body_index)
{
    std::vector<Quote> out;
    if (body.IsNull()) return out;

    Bnd_Box box;
    BRepBndLib::AddOptimal(body, box, Standard_False, Standard_False);
    if (box.IsVoid()) return out;
    double x0, y0, z0, x1, y1, z1;
    box.Get(x0, y0, z0, x1, y1, z1);
    const Vec3d lo(x0, y0, z0), hi(x1, y1, z1);
    for (int ax = 0; ax < 3; ++ax) {
        Quote q;
        q.kind  = Kind::Extent;
        q.axis  = ax;
        q.a     = lo;
        q.b     = hi;
        q.value = hi[ax] - lo[ax];
        q.body  = body_index;
        if (q.value > 1e-6) out.push_back(std::move(q));
    }

    std::vector<Piece> pieces;
    for (TopExp_Explorer ex(body, TopAbs_FACE); ex.More(); ex.Next()) {
        Piece p;
        if (cylinder_piece(TopoDS::Face(ex.Current()), p) && p.radius > 1e-3) pieces.push_back(p);
    }

    // Halves of one cylinder (a seam a Boolean or a STEP file left in) come back as the one cylinder they are.
    std::vector<Piece> whole;
    for (const Piece& p : pieces) {
        auto it = std::find_if(whole.begin(), whole.end(), [&](const Piece& w) { return same_cylinder(w, p); });
        if (it == whole.end()) whole.push_back(p);
        else it->span += p.span;
    }

    // One quote per size: "4x Ø6" is one line on a drawing, not four.
    std::vector<Quote> sized;
    for (const Piece& w : whole) {
        const bool full = w.span > 2.0 * kPi - 1e-3;
        const Kind kind = full ? Kind::Diameter : Kind::Radius;
        auto it = std::find_if(sized.begin(), sized.end(), [&](const Quote& q) {
            return q.kind == kind && q.concave == w.concave && std::abs(q.value - w.radius) < 1e-6;
        });
        if (it == sized.end()) {
            Quote q;
            q.kind    = kind;
            q.value   = w.radius;
            q.concave = w.concave;
            q.body    = body_index;
            q.spots.push_back(w.spot);
            sized.push_back(std::move(q));
        } else
            it->spots.push_back(w.spot);
    }
    // Holes first, then rounds; the largest first inside each, so the cap below drops the smallest.
    std::stable_sort(sized.begin(), sized.end(), [](const Quote& a, const Quote& b) {
        if (a.kind != b.kind) return a.kind == Kind::Diameter;
        return a.value > b.value;
    });
    constexpr size_t kMaxSized = 24;   // a body with more sizes than this is a mesh in disguise
    if (sized.size() > kMaxSized) sized.resize(kMaxSized);
    for (Quote& q : sized) out.push_back(std::move(q));
    hexagon_quotes(body, body_index, out);
    return out;
}

void link_features(std::vector<Quote>& quotes, const CadDocument& doc)
{
    for (Quote& q : quotes) {
        q.feature = -1;
        for (size_t i = 0; i < doc.features.size(); ++i) {
            const CadFeature& f = doc.features[i];
            if (!f.enabled) continue;
            if (q.kind == Kind::Diameter && f.type == CadFeatureType::Hole && std::abs(0.5 * f.hole_diameter - q.value) < 1e-6) { q.feature = int(i); break; }
            if (q.kind == Kind::Radius && f.type == CadFeatureType::Fillet && f.dressup_size2 < 0.0 && std::abs(f.dressup_size - q.value) < 1e-6) { q.feature = int(i); break; }
        }
    }
}

} } // namespace Slic3r::Quotes
