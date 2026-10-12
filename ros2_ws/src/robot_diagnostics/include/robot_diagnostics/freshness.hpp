#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace robot_diagnostics
{
constexpr uint8_t OK = 0, WARN = 1, ERROR = 2, STALE = 3;
inline std::string number(double value)
{
  std::ostringstream out;
  out << std::setprecision(17) << value;
  return out.str();
}
struct Policy
{
  double warn_seconds{0.5}, error_seconds{1.0}, future_seconds{0.1}, clock_stall_seconds{2.0};
  void validate() const
  {
    for (double value : {warn_seconds, error_seconds, future_seconds, clock_stall_seconds}) {
      if (!std::isfinite(value) || value <= 0) {
        throw std::invalid_argument("Freshness thresholds must be finite positive numbers");
      }
    }
    if (warn_seconds >= error_seconds) {
      throw std::invalid_argument("Warning age must be less than error age");
    }
  }
};
struct Status
{
  uint8_t level;
  std::string reason;
  std::map<std::string, std::string> values;
};
class Monitor
{
public:
  explicit Monitor(std::vector<std::string> streams, Policy policy = {})
  : streams_(std::move(streams)), policy_(policy)
  {
    policy_.validate();
    if (streams_.empty() || std::set<std::string>(streams_.begin(), streams_.end()).size() !=
      streams_.size())
    {
      throw std::invalid_argument("Streams must be nonempty and unique");
    }
  }
  void reset_clock()
  {
    samples_.clear(); last_ros_ns_.reset(); last_advance_ = 0; blocked_ = true; ++epoch_;
  }
  void observe(const std::string & stream, int64_t stamp, int64_t now, double steady)
  {
    if (std::find(streams_.begin(), streams_.end(), stream) == streams_.end()) {
      throw std::invalid_argument("Unknown stream: " + stream);
    }
    clock(now, steady);
    if (blocked_) {return;}
    const auto prior = samples_.find(stream);
    const Sample * previous = prior == samples_.end() ? nullptr : &prior->second;
    std::string error;
    if (stamp <= 0) {error = "invalid_stamp";} else if (
      static_cast<double>(stamp - now) > policy_.future_seconds * 1e9)
    {
      error = "future_stamp";
    } else if (previous && stamp < previous->stamp) {error = "stamp_regressed";}
    int count = 0;
    if (error.empty()) {
      const bool expired = previous && (
        static_cast<double>(now - previous->receipt) > policy_.error_seconds * 1e9 ||
        static_cast<double>(now - previous->stamp) > policy_.error_seconds * 1e9);
      if (!previous || !previous->error.empty() || expired) {count = 1;} else if (
        stamp > previous->stamp)
      {
        count = std::min(previous->advancing + 1, 2);
      } else {count = previous->advancing;}
    }
    samples_[stream] = {std::max<int64_t>(0, stamp), now, count, error};
  }
  std::map<std::string, Status> evaluate(int64_t now, double steady)
  {
    const std::string reason = clock(now, steady);
    const std::map<std::string, std::string> common{
      {"schema_version", "1"}, {"clock_epoch", std::to_string(epoch_)}};
    std::map<std::string, Status> result{{"clock", {blocked_ ? STALE : OK, reason, common}}};
    for (const auto & stream : streams_) {
      Status status{STALE, "not_observed", common};
      const auto found = samples_.find(stream);
      if (blocked_) {status.reason = reason;} else if (found != samples_.end()) {
        const auto & sample = found->second;
        const double receipt_age = static_cast<double>(now - sample.receipt) / 1e9;
        const double stamp_age = static_cast<double>(now - sample.stamp) / 1e9;
        status.values.insert({
          {"receipt_age_seconds", number(receipt_age)}, {"stamp_age_seconds", number(stamp_age)},
          {"stamp_ns", std::to_string(sample.stamp)},
          {"advancing_samples", std::to_string(sample.advancing)},
          {"warn_seconds", number(policy_.warn_seconds)},
          {"error_seconds", number(policy_.error_seconds)}});
        if (receipt_age > policy_.error_seconds) {status.reason = "receipt_timeout";} else if (
          !sample.error.empty())
        {
          status.level = ERROR; status.reason = sample.error;
        } else if (stamp_age > policy_.error_seconds) {
          status.level = ERROR; status.reason = "stamp_timeout";
        } else if (std::max(receipt_age, stamp_age) > policy_.warn_seconds) {
          status.level = WARN; status.reason = "age_warning";
        } else if (sample.advancing < 2) {status.reason = "awaiting_advancing_samples";} else {
          status.level = OK; status.reason = "fresh";
        }
      }
      result[stream] = std::move(status);
    }
    return result;
  }
private:
  struct Sample {int64_t stamp, receipt; int advancing; std::string error;};
  std::string clock(int64_t now, double steady)
  {
    if (now <= 0) {
      if (last_ros_ns_) {samples_.clear(); ++epoch_;}
      last_ros_ns_.reset(); last_advance_ = 0; blocked_ = true;
      return "clock_uninitialized";
    }
    const bool backward = last_ros_ns_ && now < *last_ros_ns_;
    const bool advancing = !last_ros_ns_ || now > *last_ros_ns_;
    if (backward || (advancing && blocked_)) {samples_.clear(); ++epoch_;}
    if (advancing || backward) {last_advance_ = steady;}
    last_ros_ns_ = now;
    blocked_ = steady - last_advance_ > policy_.clock_stall_seconds;
    return blocked_ ? "clock_not_advancing" : "clock_advancing";
  }
  std::vector<std::string> streams_;
  Policy policy_;
  std::map<std::string, Sample> samples_;
  std::optional<int64_t> last_ros_ns_;
  double last_advance_{0};
  bool blocked_{true};
  uint64_t epoch_{0};
};
}  // namespace robot_diagnostics
