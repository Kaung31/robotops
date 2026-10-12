#pragma once
#include <cstdint>
#include <optional>
#include <stdexcept>

namespace fault_injection
{
// Wall-time acquisition liveness, independent of deliberately suppressed output.
// Disabled by default; only the explicitly owned simulation probe opts in.
class InputWatchdog
{
public:
  InputWatchdog(int64_t timeout, int64_t startup, int64_t start)
      : timeout_(timeout), startup_(startup), start_(start)
  {
    if (timeout < 0 || timeout > 30000000000LL || startup <= 0 || startup > 60000000000LL)
      throw std::invalid_argument("invalid upstream scan watchdog bounds");
  }
  void observe(int64_t now) { last_ = now; }
  const char *failure(int64_t now) const
  {
    if (!enabled())
      return nullptr;
    const auto origin = last_.value_or(start_);
    if (now < origin)
      return "upstream watchdog wall clock regressed";
    if (now - origin > (last_ ? timeout_ : startup_))
      return last_ ? "upstream_scan_timeout" : "upstream_scan_startup_timeout";
    return nullptr;
  }
  bool enabled() const { return timeout_ > 0; }

private:
  int64_t timeout_, startup_, start_;
  std::optional<int64_t> last_;
};
} // namespace fault_injection
