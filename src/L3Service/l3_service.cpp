// L3 — TaglIAtelle kernel service. See l3_service.hpp for the contract.
//
// Design notes (deliberate, keep them true):
//  * Deterministic + serial. The server thread blocks in accept() and services
//    exactly one client at a time. There is no wx main-thread marshal, no
//    timeout, no randomness: the same request line yields the same response
//    line. The only time-keeping is status.uptime_seconds (explicitly required).
//  * OCCT errors are NOT std::exception, so every dispatch catches
//    Standard_Failure BEFORE std::exception, then a final `...` so no local
//    client (a world-owned /tmp socket) can take the process down.
//  * Crypto is self-contained: a base64 decoder and an FNV-1a 64-bit recipe
//    digest live here, so this target has zero OpenSSL link surface.

#include "l3_service.hpp"

// Kernel (libslic3r public surface)
#include "libslic3r/CAD/CadDocument.hpp"
#include "libslic3r/CAD/SketchImport.hpp"
#include "libslic3r/ClipperUtils.hpp"   // _clipper_ex, Slic3r::Polygons/ExPolygons
#include "libslic3r/Polygon.hpp"        // Slic3r::Polygon::new_scale
#include "libslic3r/Point.hpp"          // unscale, Vec2d
#include "libslic3r/Utils.hpp"          // set_resources_dir (bundled-font root)
#include <Standard_Failure.hxx>         // Standard_Failure (OCCT)

#include <nlohmann/json.hpp>

// POSIX Unix-socket server + signal-driven shutdown
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <unistd.h>
#include <csignal>

#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>

// The kernel headers declare their types in `namespace Slic3r` (CadDocument,
// BooleanMode, CadFeatureType, ExtrudeEnd, SketchPlane, ImportRegions, Polygons,
// ExPolygons, ClipperLib, text_to_regions, ...). Pull the whole kernel namespace
// in: this is a thin kernel-facing service, not a library that must keep its
// namespace clean.
using namespace Slic3r;

// Force extraction of LocalesUtils.o from the static kernel archive. This is a
// minimal binary that references far fewer kernel symbols than the GUI or the
// test executable, so `LocalesUtils.o` would otherwise go unextracted until the
// linker has already passed the kernel archive; the admesh deps archive then
// references `CNumericLocalesSetter` too late -> undefined reference. Referencing
// one LocalesUtils symbol here (observably, via a volatile) pulls the TU in
// during the first scan of libslic3r.a. This is surgical: unlike whole-archive
// it does not drag in unrelated optional TUs (SVG, flush-volume). (The
// `--start-group` in CMakeLists.txt does not reliably reach admesh.a, so this
// anchor is the deterministic fix for this particular reverse dependency.)
[[maybe_unused]] static volatile bool s_locale_anchor =
    Slic3r::is_decimal_separator_point();

namespace {

using json = nlohmann::json;

// --- self-contained base64 decode (no OpenSSL) -------------------------------
// Returns the decoded bytes. Ignores '=', CR, LF and whitespace. A lone
// trailing 6-bit unit (len%4==1) is dropped — it is invalid base64 and decodes
// to nothing meaningful; every legal input round-trips exactly.
std::string base64_decode(const std::string& in)
{
    auto val64 = [](char c) -> long {
        if (c >= 'A' && c <= 'Z') return long(c - 'A');
        if (c >= 'a' && c <= 'z') return long(c - 'a') + 26;
        if (c >= '0' && c <= '9') return long(c - '0') + 52;
        if (c == '+' || c == '-') return 62;
        if (c == '/' || c == '_') return 63;
        return -1;
    };

    std::string clean;
    clean.reserve(in.size());
    for (char c : in)
        if (c != '=' && c != '\n' && c != '\r' && c != ' ' && c != '\t')
            clean.push_back(c);

    std::string out;
    out.reserve(clean.size() * 3 / 4 + 2);
    const size_t full = clean.size() / 4;
    for (size_t i = 0; i < full; ++i) {
        const long a  = val64(clean[i*4+0]);
        const long b  = val64(clean[i*4+1]);
        const long cc = val64(clean[i*4+2]);
        const long d  = val64(clean[i*4+3]);
        if (a < 0 || b < 0 || cc < 0 || d < 0)
            out.append(3, char(0));   // malformed group: emit nulls, do not throw
        else {
            const long v = (a << 18) | (b << 12) | (cc << 6) | d;
            out.push_back(char((v >> 16) & 0xFF));
            out.push_back(char((v >> 8)  & 0xFF));
            out.push_back(char(v         & 0xFF));
        }
    }
    const size_t r = clean.size() % 4;
    const size_t i = clean.size() - r;
    const long a = val64(clean[i]);
    if (r == 2) {
        if (a >= 0) {
            const long b = val64(clean[i+1]);
            if (b >= 0) out.push_back(char(((a << 6) | b) >> 4));
        }
    } else if (r == 3) {
        if (a >= 0) {
            const long b  = val64(clean[i+1]);
            const long cc = val64(clean[i+2]);
            if (b >= 0 && cc >= 0) {
                const long v = (a << 12) | (b << 6) | cc;
                out.push_back(char((v >> 10) & 0xFF));
                out.push_back(char((v >> 2)  & 0xFF));
            }
        }
    }
    return out;
}

// --- FNV-1a 64-bit digest of the serialised recipe (stable across recomputes)
uint64_t fnv1a64(const std::string& s)
{
    uint64_t h = 1469598103934665603ULL;   // FNV offset basis
    const uint64_t p = 1099511628211ULL;   // FNV prime
    for (unsigned char c : s) { h ^= c; h *= p; }
    return h;
}

std::string hex64(uint64_t v)
{
    static const char* digits = "0123456789abcdef";
    char buf[16];
    for (int i = 15; i >= 0; --i) { buf[i] = digits[v & 0xF]; v >>= 4; }
    return std::string("0x").append(buf, 16);
}

// --- JSON-RPC envelope (mirrors GUI/CAD/McpControl.cpp) ----------------------
std::string rpc_result(const json& id, const json& result)
{ return json{{"jsonrpc", "2.0"}, {"id", id}, {"result", result}}.dump(); }
std::string rpc_error(const json& id, int code, const std::string& msg)
{ return json{{"jsonrpc", "2.0"}, {"id", id},
              {"error", {{"code", code}, {"message", msg}}}}.dump(); }

// Resolve a key with an alias: return the first present, else nullptr.
const json* find_obj(const json& p, const char* a, const char* b)
{ if (p.contains(a)) return &p[a];
  if (p.contains(b)) return &p[b];
  return nullptr; }

// CadFeatureType index -> short name (order MUST match CadDocument.hpp:22).
const char* feature_type_name(CadFeatureType t)
{
    static const char* names[] = {
        "Sketch","Extrude","Fillet","Chamfer","Hole","Thread","Shell","Revolve",
        "Sweep","Pattern","Plane","Loft","Draft","Import","Boolean","Cut","Mirror",
        "Axis","CoordSys","Helix","Transform","Thicken","Project","DeleteFace","Rib",
        "SurfaceExtrude","SurfaceRevolve","ThickenSurface","SurfaceOffset",
        "SurfaceLoft","SurfaceFill","Mate" };
    const size_t i = static_cast<size_t>(t);
    return i < 32u ? names[i] : "Unknown";
}

BooleanMode parse_boolean_mode(const std::string& s)
{
    if (s == "Add")       return BooleanMode::Add;
    if (s == "Cut")       return BooleanMode::Cut;
    if (s == "Intersect") return BooleanMode::Intersect;
    return BooleanMode::New;               // default + explicit "New"
}

// A JSON array of loops (array of [x,y]) -> Slic3r::Polygons in fixed-point mm.
Slic3r::Polygons to_polygons(const json& loops)
{
    Slic3r::Polygons out;
    if (!loops.is_array())
        throw std::invalid_argument("expected an array of loops (each loop: array of [x,y])");
    for (const auto& loop : loops) {
        if (!loop.is_array())
            throw std::invalid_argument("each loop must be an array of [x,y] points");
        std::vector<Slic3r::Vec2d> pts;
        for (const auto& pt : loop) {
            if (!pt.is_array() || pt.size() < 2 || !pt[0].is_number() || !pt[1].is_number())
                throw std::invalid_argument("each point must be a numeric [x, y] pair (mm)");
            pts.emplace_back(double(pt[0]), double(pt[1]));
        }
        if (pts.size() < 3)
            throw std::invalid_argument("a loop must have at least 3 distinct points");
        out.emplace_back(Slic3r::Polygon::new_scale(pts));
    }
    return out;
}

json loop_to_json(const Slic3r::Polygon& p)
{
    json l = json::array();
    for (const auto& pt : p.points) {
        const Slic3r::Vec2d mm = Slic3r::unscale(pt);   // coord_t (fixed) -> mm (double)
        l.push_back(json::array({ mm.x(), mm.y() }));
    }
    return l;
}

// --- the five methods (pure: params -> result json; throw on bad input) --------

json handle_status(std::chrono::steady_clock::time_point t0, bool valid_start)
{
    json r;
    r["service"]        = "snaporca-l3";
    r["protocol"]       = "jsonrpc-2.0";
    r["version"]        = orca_l3::Service::kVersion;
    r["recipe_version"] = CadDocument::ORCA_CAD_RECIPE_VERSION;
#ifdef SLIC3R_VERSION
    r["kernel_version"] = SLIC3R_VERSION;
#endif
    r["methods"] = json::array({ "status", "recipe.decode", "recipe.apply",
                                 "sketch.boolean2d", "sketch.text" });
    if (valid_start) {
        const auto now = std::chrono::steady_clock::now();
        r["uptime_seconds"] = std::chrono::duration_cast<std::chrono::seconds>(now - t0).count();
    } else {
        r["uptime_seconds"] = 0;
    }
    return r;
}

json handle_recipe_decode(const json& params)
{
    if (!params.is_object() || !params.contains("recipe") || !params["recipe"].is_string())
        throw std::invalid_argument("recipe.decode: params.recipe must be a base64 string");

    const std::string blob = base64_decode(params["recipe"].get<std::string>());

    CadDocument doc;
    const bool ok = doc.deserialize_recipe(blob);

    json r;
    r["ok"]             = ok;
    r["recipe_version"] = CadDocument::ORCA_CAD_RECIPE_VERSION;
    r["recipe_bytes"]   = blob.size();
    r["feature_count"]  = doc.features.size();
    r["body_count"]     = doc.bodies.size();
    r["variable_count"] = doc.variables.size();

    json vars = json::object();
    for (const auto& kv : doc.variables) vars[kv.first] = kv.second;
    r["variables"] = std::move(vars);

    json features = json::array();
    for (const auto& f : doc.features) {
        json fe;
        fe["type"]    = feature_type_name(f.type);
        fe["name"]    = f.name;
        fe["enabled"] = f.enabled;
        if (!f.expr.empty()) {
            json e = json::object();
            for (const auto& kv : f.expr) e[kv.first] = kv.second;
            fe["expr"] = std::move(e);
        }
        features.push_back(std::move(fe));
    }
    r["features"] = std::move(features);
    if (!ok) r["error"] = "not a valid ORCA CAD recipe blob (cereal format / version mismatch)";
    return r;
}

json handle_recipe_apply(const json& params)
{
    if (!params.is_object() || !params.contains("recipe") || !params["recipe"].is_string())
        throw std::invalid_argument("recipe.apply: params.recipe (base64) required");

    const std::string blob = base64_decode(params["recipe"].get<std::string>());
    CadDocument doc;
    const bool deserialized = doc.deserialize_recipe(blob);

    // (a) Optional text feature. A single Extrude with imported_regions routes
    //     through SketchEngine::make_extrude_regions on recompute
    //     (CadDocument.cpp:2215), so the kernel materialises the body — we do
    //     not call make_extrude_regions ourselves.
    int    text_index = -1;
    size_t text_regions = 0, text_vertices = 0;
    if (params.contains("text") && params["text"].is_object()) {
        const json& t = params["text"];
        const std::string utf8 = t.value("utf8", std::string());
        const double      size = t.value("size_mm", 5.0);
        const std::string font = t.value("font_path", std::string());
        const double      h    = t.value("height_mm", 5.0);
        const double      ox   = t.value("x", 0.0);
        const double      oy   = t.value("y", 0.0);
        if (utf8.empty())
            throw std::invalid_argument("recipe.apply: text.utf8 is required when text is present");
        const Slic3r::ImportRegions regions = Slic3r::text_to_regions(utf8, size, font);
        if (regions.empty())
            throw std::runtime_error("recipe.apply: text vectorisation produced no regions (font missing?)");
        CadFeature tf;
        tf.type             = CadFeatureType::Extrude;
        tf.name             = "l3_text";
        tf.plane            = SketchPlane::XY();
        tf.imported_regions = regions;
        tf.import_offset    = Slic3r::Vec2d(ox, oy);
        tf.import_scale_x   = 1.0;
        tf.import_scale_y   = 1.0;
        tf.sketch_ref       = -1;                       // self; routes via imported_regions
        tf.distance         = h;
        tf.symmetric        = false;
        tf.mode             = parse_boolean_mode(t.value("mode", std::string("New")));
        tf.extrude_end      = ExtrudeEnd::Blind;
        text_regions        = regions.size();
        for (const auto& rr : regions) for (const auto& lp : rr) text_vertices += lp.size();
        doc.features.push_back(std::move(tf));
        text_index = int(doc.features.size()) - 1;
    }

    // (b) Recompute #1: materialise the frozen body (+ text) so any session-scoped
    //     edge ids in a `project` step name THIS generation's topology.
    int  n_recompute = 0;
    bool recompute_ok = true;
    recompute_ok &= doc.recompute();
    n_recompute++;

    // (c) Optional edge->sketch projection of the workpiece contour, then
    //     recompute #2 so the new construction references are applied.
    bool did_project = false;
    int  projected   = -1;
    if (params.contains("project") && params["project"].is_object()) {
        const json& p    = params["project"];
        const int   sf   = p.value("sketch_feature", text_index >= 0 ? text_index : 0);
        const int   sb   = p.value("source_body",   0);
        const int   face = p.value("face",          0);
        std::vector<int> eids;
        if (p.contains("edge_ids") && p["edge_ids"].is_array())
            for (const auto& e : p["edge_ids"])
                if (e.is_number_integer()) eids.push_back(e.get<int>());
        projected    = doc.project_edges_into_sketch(sf, sb, eids, face);
        did_project  = true;
        recompute_ok &= doc.recompute();
        n_recompute++;
    }

    // (d) Deterministic digest over the canonical serialisation.
    std::string ser;
    bool ser_ok = true;
    try { ser = doc.serialize_recipe(); }
    catch (const std::exception&) { ser_ok = false; ser.clear(); }

    json r;
    r["ok"]              = bool(deserialized && recompute_ok && ser_ok
                                && (!did_project || projected >= 0));
    r["deserialized"]    = deserialized;
    r["recompute_ok"]    = recompute_ok;
    r["recompute_count"] = n_recompute;
    r["feature_count"]   = doc.features.size();
    r["body_count"]      = doc.bodies.size();
    r["recipe_bytes"]    = blob.size();
    r["serialized_bytes"]= ser.size();
    r["digest"]          = hex64(fnv1a64(ser));
    if (!doc.error.empty()) r["error"] = doc.error;

    if (text_index >= 0) {
        json a;
        a["feature_index"] = text_index;
        a["region_count"]  = text_regions;
        a["vertex_count"]  = text_vertices;
        r["applied_text"]  = std::move(a);
    }
    if (did_project) {
        json a;
        a["projected"] = projected;
        a["valid"]     = projected >= 0;
        r["applied_project"] = std::move(a);
    }
    return r;
}

json handle_boolean2d(const json& params)
{
    if (!params.is_object())
        throw std::invalid_argument("sketch.boolean2d: params object required");
    const std::string op = params.value("op", std::string("union"));
    const json* subj = find_obj(params, "subject", "subject_loops");
    const json* clip = find_obj(params, "clip",    "clip_loops");
    if (!subj || !subj->is_array())
        throw std::invalid_argument("sketch.boolean2d: params.subject (array of loops) required");
    if (!clip || !clip->is_array())
        throw std::invalid_argument("sketch.boolean2d: params.clip (array of loops) required");

    const Slic3r::Polygons subject = to_polygons(*subj);
    const Slic3r::Polygons clipr   = to_polygons(*clip);

    // Map the requested op onto the public, always-linked ClipperUtils helpers
    // (union_ex / intersection_ex / diff_ex / xor_ex). The lower-level
    // _clipper_ex is a BBS helper that is not reliably present in the static
    // kernel link, so we deliberately avoid it. Both operands are converted to
    // ExPolygons (single outer ring, no holes) so one overload set serves all
    // four ops.
    Slic3r::ExPolygons subj_ep;
    subj_ep.reserve(subject.size());
    for (const auto& p : subject) subj_ep.emplace_back(p);
    Slic3r::ExPolygons clip_ep;
    clip_ep.reserve(clipr.size());
    for (const auto& p : clipr) clip_ep.emplace_back(p);

    Slic3r::ExPolygons result;
    if      (op == "union")        result = Slic3r::union_ex(subj_ep);
    else if (op == "intersection") result = Slic3r::intersection_ex(subj_ep, clip_ep);
    else if (op == "difference")   result = Slic3r::diff_ex(subj_ep, clip_ep);
    else if (op == "xor")          result = Slic3r::xor_ex(subj_ep, clip_ep);
    else throw std::invalid_argument("sketch.boolean2d: op must be "
                                     "union|intersection|difference|xor");

    json loops = json::array();
    for (const auto& ep : result) {
        loops.push_back(loop_to_json(ep.contour));      // outer
        for (const auto& h : ep.holes) loops.push_back(loop_to_json(h));
    }
    json r;
    r["op"]           = op;
    r["region_count"] = result.size();
    r["loop_count"]   = loops.size();
    r["loops"]        = std::move(loops);
    return r;
}

json handle_text(const json& params)
{
    if (!params.is_object())
        throw std::invalid_argument("sketch.text: params object required");
    const std::string utf8 = params.value("utf8", std::string());
    const double      size = params.value("size_mm", 5.0);
    const std::string font = params.value("font_path", std::string());
    const double      ox   = params.value("x", 0.0);
    const double      oy   = params.value("y", 0.0);
    const double      sx   = params.value("scale_x", 1.0);
    const double      sy   = params.value("scale_y", 1.0);
    if (utf8.empty())
        throw std::invalid_argument("sketch.text: params.utf8 must be a non-empty string");
    if (!(size > 0.0))
        throw std::invalid_argument("sketch.text: params.size_mm must be > 0 (mm)");

    const Slic3r::ImportRegions regions = Slic3r::text_to_regions(utf8, size, font);
    if (regions.empty())
        throw std::runtime_error("sketch.text: no glyphs produced (font missing or unparseable?)");

    // Apply the placement transform to the report so loops come back in world mm.
    const Slic3r::ImportRegions placed =
        Slic3r::transform_regions(regions, Slic3r::Vec2d(ox, oy), sx, sy);

    json loops = json::array();
    size_t verts = 0;
    for (const auto& region : placed)
        for (const auto& loop : region) {
            json l = json::array();
            for (const auto& p : loop) l.push_back(json::array({ p(0), p(1) }));
            verts += loop.size();
            loops.push_back(std::move(l));
        }

    json r;
    r["utf8"]         = utf8;
    r["size_mm"]      = size;
    r["font_path"]    = font.empty() ? std::string("<bundled-default>") : font;
    r["region_count"] = regions.size();
    r["loop_count"]   = loops.size();
    r["vertex_count"] = verts;
    r["loops"]        = std::move(loops);
    return r;
}

} // namespace

// ---------------------------------------------------------------------------
// Service: socket lifecycle + dispatch
// ---------------------------------------------------------------------------

bool orca_l3::Service::start(const std::string& sock)
{
    if (running_) return false;
    sock_path_ = sock;
    t0_ = std::chrono::steady_clock::now();
    stop_flag_ = false;

    std::thread t([this]() {
        ::unlink(sock_path_.c_str());
        int sfd = ::socket(AF_UNIX, SOCK_STREAM, 0);
        if (sfd < 0) { running_ = false; stop_flag_ = true; return; }

        sockaddr_un addr{};
        addr.sun_family = AF_UNIX;
        std::strncpy(addr.sun_path, sock_path_.c_str(), sizeof(addr.sun_path) - 1);

        // Owner-only (0600), no window where a wider mode exists; the chmod
        // covers platforms that do not apply umask to sockets.
        const mode_t old_umask = ::umask(0177);
        const int bind_rc = ::bind(sfd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
        ::umask(old_umask);
        if (bind_rc < 0) { ::close(sfd); running_ = false; stop_flag_ = true; return; }
        if (::chmod(sock_path_.c_str(), S_IRUSR | S_IWUSR) < 0) {
            ::close(sfd); ::unlink(sock_path_.c_str());
            running_ = false; stop_flag_ = true; return;
        }
        if (::listen(sfd, 1) < 0) { ::close(sfd); running_ = false; stop_flag_ = true; return; }

        sfd_     = sfd;
        running_ = true;

        for (;;) {
            int cfd = ::accept(sfd, nullptr, nullptr);
            if (cfd >= 0 && stop_flag_) { ::close(cfd); break; }   // shutdown wake-up
            if (cfd < 0) continue;
            serve_client(cfd);
            ::close(cfd);
        }
    });

    // Bounded settle wait (up to ~250 ms) for the socket to be listening. Not a
    // long poll — it is the minimum required for a caller that immediately
    // probes for `status` to see a live socket.
    for (int i = 0; i < 50 && !(running_ && sfd_ > 0); ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(5));

    server_thread_ = std::move(t);
    return running_ && sfd_ > 0;
}

void orca_l3::Service::stop()
{
    stop_flag_ = true;
    running_   = false;
    if (sfd_ >= 0) {
        // Wake the blocking accept() by making a self-connection; the loop
        // notices stop_flag_ and exits the moment accept() returns.
        if (!sock_path_.empty()) {
            int w = ::socket(AF_UNIX, SOCK_STREAM, 0);
            if (w >= 0) {
                sockaddr_un a{}; a.sun_family = AF_UNIX;
                std::strncpy(a.sun_path, sock_path_.c_str(), sizeof(a.sun_path) - 1);
                ::connect(w, reinterpret_cast<sockaddr*>(&a), sizeof(a));   // best-effort wake
                ::close(w);
            }
        }
        ::shutdown(sfd_, SHUT_RDWR);
        ::close(sfd_);
        sfd_ = -1;
    }
    if (server_thread_.joinable()) {
        try { server_thread_.join(); } catch (const std::exception&) {}
    }
    if (!sock_path_.empty()) { ::unlink(sock_path_.c_str()); sock_path_.clear(); }
}

void orca_l3::Service::serve_client(int cfd)
{
    std::string buf;
    char chunk[4096];
    for (;;) {
        const ssize_t n = ::read(cfd, chunk, sizeof(chunk));
        if (n <= 0) break;
        buf.append(chunk, size_t(n));
        size_t nl;
        while ((nl = buf.find('\n')) != std::string::npos) {
            const std::string line  = buf.substr(0, nl);
            buf.erase(0, nl + 1);
            if (line.empty()) continue;
            const std::string reply = handle_line(line);   // no trailing newline
            std::string out = reply;
            out.push_back('\n');
#ifdef MSG_NOSIGNAL
            if (::send(cfd, out.data(), out.size(), MSG_NOSIGNAL) < 0) return;
#else
            if (::write(cfd, out.data(), out.size()) < 0) return;   // SO_NOSIGPIPE at accept
#endif
        }
    }
}

std::string orca_l3::Service::handle_line(const std::string& line) const
{
    json req;
    try { req = json::parse(line); }
    catch (const std::exception& ex) {
        return rpc_error(json(nullptr), -32700, std::string("parse error: ") + ex.what());
    }

    const json        id     = req.contains("id")     ? req["id"]     : json(nullptr);
    const std::string method = req.value("method", std::string());
    const json        params = req.contains("params") ? req["params"] : json::object();
    if (method.empty())
        return rpc_error(id, -32600, "missing method");

    const bool valid_start = (sfd_ > 0);
    try {
        if (method == "status")            return rpc_result(id, handle_status(t0_, valid_start));
        if (method == "recipe.decode")     return rpc_result(id, handle_recipe_decode(params));
        if (method == "recipe.apply")      return rpc_result(id, handle_recipe_apply(params));
        if (method == "sketch.boolean2d")  return rpc_result(id, handle_boolean2d(params));
        if (method == "sketch.text")       return rpc_result(id, handle_text(params));
        return rpc_error(id, -32601, "Unknown method: " + method);
    } catch (const Standard_Failure& ex) {
        // OCCT's Standard_Failure is not a std::exception — catch it first so
        // the message reads and the process does not terminate().
        return rpc_error(id, -32000,
            std::string("OCCT: ") + (ex.GetMessageString() ? ex.GetMessageString() : "failure"));
    } catch (const std::invalid_argument& ex) {
        return rpc_error(id, -32602, ex.what());
    } catch (const std::exception& ex) {
        return rpc_error(id, -32000, ex.what());
    } catch (...) {
        return rpc_error(id, -32000, "internal error: unknown exception");
    }
}

orca_l3::Service::~Service() { stop(); }

// ---------------------------------------------------------------------------
// CLI entry
// ---------------------------------------------------------------------------

namespace {

volatile sig_atomic_t g_shutdown = 0;
void on_signal(int) { g_shutdown = 1; }   // async-signal-safe: single store

void usage()
{
    std::fputs(
        "l3_service [--socket PATH] [--resources PATH]\n"
        "  --socket PATH     Unix-socket path (default: $SNAPORCA_L3_SOCK or /tmp/snaporca-l3.sock)\n"
        "                    Use a DIFFERENT path per smoke test to avoid a stale socket file.\n"
        "  --resources PATH  resources dir (default: $SNAPORCA_RESOURCES, else <cwd>/resources).\n"
        "                    Required for sketch.text glyph outlines (bundled font lives under\n"
        "                    resources/fonts/).\n"
        "  -h, --help       Show this help and exit.\n"
        "\n"
        "Smoke-test from another terminal:\n"
        "  echo '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"status\"}' | nc -U /tmp/probe.sock\n",
        stderr);
}

} // namespace

int main(int argc, char** argv)
{
    std::string sock;
    if (const char* env = ::getenv("SNAPORCA_L3_SOCK"))
        if (env[0] != '\0') sock = env;
    sock = sock.empty() ? std::string("/tmp/snaporca-l3.sock") : sock;

    std::string resources;
    if (const char* env = ::getenv("SNAPORCA_RESOURCES"))
        if (env[0] != '\0') resources = env;

    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--socket" || a == "--sock") {
            if (i + 1 >= argc) { usage(); return 2; }
            sock = argv[++i];
        } else if (a == "--resources") {
            if (i + 1 >= argc) { usage(); return 2; }
            resources = argv[++i];
        } else if (a == "--help" || a == "-h") {
            usage();
            return 0;
        } else if (!a.empty() && a[0] == '-' && a != "-") {
            std::fprintf(stderr, "l3_service: unknown option '%s' (try --help)\n", a.c_str());
            usage();
            return 2;
        }
    }

    // SketchImport resolves the bundled default font relative to resources_dir().
    // A standalone binary has no GUI to call set_resources_dir(), so do it here
    // from an explicit --resources / $SNAPORCA_RESOURCES, else <cwd>/resources.
    if (resources.empty())
        resources = "resources";
    Slic3r::set_resources_dir(resources);

    orca_l3::Service svc;
    if (!svc.start(sock)) {
        std::fprintf(stderr, "l3_service: failed to bind %s (path in use? parent directory absent?)\n",
                     sock.c_str());
        return 1;
    }
    std::fprintf(stderr, "l3_service: listening on %s "
        "(methods: status, recipe.decode, recipe.apply, sketch.boolean2d, sketch.text) — Ctrl-C to stop.\n",
        sock.c_str());

    ::signal(SIGINT, on_signal);
    ::signal(SIGTERM, on_signal);

    // Serial service: each accepted client is handled fully by the server
    // thread. main() only here keeps the process alive until interrupted.
    for (;;) {
        if (g_shutdown) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    svc.stop();
    return 0;
}
