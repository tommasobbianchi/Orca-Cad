#ifndef Slic3r_L3Service_hpp_
#define Slic3r_L3Service_hpp_

#include <atomic>
#include <chrono>
#include <string>
#include <thread>

// L3 — TaglIAtelle kernel service: a standalone, headless JSON-RPC 2.0 front-end
// for the Orca CAD kernel (libslic3r), over a Unix domain socket.
//
// Deterministic and serial: one accepted client at a time, no wx main-thread
// marshalling, no timer, no randomness. Line-delimited JSON-RPC requests ->
// line-delimited JSON-RPC responses (a single "\n" terminates each message).
//
// Methods (JSON-RPC `method` strings):
//     status
//     recipe.decode    { recipe: <base64> }
//     recipe.apply     { recipe: <base64>, text?: {...}, project?: {...} }
//     sketch.boolean2d { op, subject:[loop,...], clip:[loop,...] }   (aliases subject_loops/clip_loops)
//     sketch.text      { utf8, size_mm, font_path? }

namespace orca_l3 {

class Service {
public:
    // L3 JSON-RPC surface version. Bump on any change to the method contract.
    static constexpr const char* kVersion = "1";

    Service() = default;
    ~Service();

    Service(const Service&) = delete;
    Service& operator=(const Service&) = delete;

    // Bind/listen on `sock_path` (owner-only, 0600) and start the accept-loop
    // server thread. Returns false (leaving state clean) on bind/listen failure.
    bool start(const std::string& sock_path);
    // Idempotent: stops the server thread, closes the fd, unlinks the socket.
    void stop();

    // Deterministic single-request handler: one JSON-RPC request line in, one
    // response line out (no trailing newline). No socket, no thread — pure and
    // re-entrant per call. Exposed so the dispatch can be driven/tests without
    // touching the socket surface.
    std::string handle_line(const std::string& line) const;

    int  server_fd() const { return sfd_; }
    bool running() const { return running_; }

private:
    void serve_client(int cfd);
    void server_loop();

    int      sfd_{-1};
    std::string sock_path_;
    std::thread server_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> stop_flag_{false};
    std::chrono::steady_clock::time_point t0_;
};

} // namespace orca_l3

#endif // Slic3r_L3Service_hpp_
