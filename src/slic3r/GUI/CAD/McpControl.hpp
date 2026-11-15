#ifndef slic3r_GUI_McpControl_hpp_
#define slic3r_GUI_McpControl_hpp_

// MCP control surface: a local JSON-RPC 2.0 server, line-delimited over a Unix domain
// socket, that lets an external MCP bridge drive and perceive the Design tab. On whenever the
// CAD feature is enabled in Preferences; the env var ORCA_CAD_MCP selects the path or opts out:
//   unset, empty or 1             -> socket at /tmp/orca-cad-mcp.sock
//   ORCA_CAD_MCP=0 | off          -> no socket
//   ORCA_CAD_MCP=/path/to.sock    -> socket at that path (an existing non-socket file there is
//                                    left alone and the server does not start; a socket that
//                                    still answers is never taken over)
// The socket is created 0600 and removed at exit. All CAD work is marshalled onto the wx main
// thread and runs through the SAME CadDocument kernel the GUI uses (no parallel engine);
// describe_tools lists the methods. A method that changes the document is refused (-32002)
// while the Design tab is busy with it — a rebuild, an open feature card, a sketch session.
//
// ponytail: Unix-socket only (POSIX). Windows compiles this to a no-op; add a named
// pipe transport when a Windows agent actually needs it.

#include <string>
#include <nlohmann/json.hpp>

namespace Slic3r { namespace GUI {

// Start the server thread unless ORCA_CAD_MCP is 0/off. Safe to call once the MainFrame exists —
// the Design panel is built on the first request. No-op when opted out or on Windows.
void start_mcp_control_if_enabled();

// Path of the control socket the app listens on (same rule as above); empty when ORCA_CAD_MCP=0|off or on Windows.
std::string mcp_socket_path();

class DesignPanel;
struct PrintNote;
// Run one automatic fix: `fix` is {"steps":[{"method":...,"params":{...}},...]}. Each step goes through the
// same dispatcher the socket uses; the first failing step stops it, undoes the steps already applied and
// throws with the verb's message. Returns {ok, applied_label, steps}.
nlohmann::json run_print_fix(DesignPanel* panel, const nlohmann::json& fix);
// The design-for-print check (analyze_printability) of body `body`, as one English line for the status line: the warnings and the
// suggestions, three at most. `clean` is true when there is nothing to report. Throws std::runtime_error when the body cannot be read.
// warnings_only: leave the suggestions out (the automatic check after a feature commit only speaks when something is actually wrong).
// pins: the issues that have a place on the part, for the viewport to mark there.
std::string print_check_summary(DesignPanel* panel, int body, bool& clean, bool warnings_only = false, std::vector<PrintNote>* pins = nullptr);

}} // namespace Slic3r::GUI

#endif // slic3r_GUI_McpControl_hpp_
