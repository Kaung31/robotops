#pragma once
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace fault_injection
{
struct Plan
{
  std::string experiment_id, trial_id, kind;
  int64_t delay_ns, duration_ns;
  void validate() const
  {
    auto identity = [](const std::string &value)
    {
      return !value.empty() && value.size() <= 128 &&
             value.find_first_not_of(
                 "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") ==
                 std::string::npos;
    };
    if (!identity(experiment_id) || !identity(trial_id))
      throw std::invalid_argument("experiment/trial identity must be 1..128 alphanumeric, _ or -");
    if (kind != "dropout" && kind != "stamp_freeze")
      throw std::invalid_argument("one explicit dropout or stamp_freeze plan required");
    if (delay_ns < 0 || delay_ns > 3600000000000LL || duration_ns < 1 ||
        duration_ns > 60000000000LL)
      throw std::invalid_argument("delay must be [0,3600] s, duration (0,60] s");
  }
};
struct Event
{
  std::string state;
  int64_t ros_ns;
  uint64_t epoch, affected;
  bool confirmed;
};
struct Decision
{
  bool suppress{false};
  bool freeze{false};
  int64_t stamp_ns{0};
};
class Policy
{
public:
  explicit Policy(Plan plan) : plan_(std::move(plan)) { plan_.validate(); }
  void tick(int64_t now, bool jumped = false)
  {
    if (jumped || (last_ > 0 && now < last_))
    {
      ++epoch_;
      if (!closed_)
        close("aborted_clock", now);
    }
    last_ = now;
    if (closed_ || now <= 0)
      return;
    if (!anchored_)
    {
      anchored_ = true;
      start_ = now + plan_.delay_ns;
      end_ = start_ + plan_.duration_ns;
    }
    if (now >= end_)
      close(affected_ ? "ended" : "expired_unapplied", now);
  }
  Decision sample(int64_t now, int64_t stamp, bool jumped = false)
  {
    tick(now, jumped);
    Decision result;
    if (closed_ || !anchored_ || now < start_)
      return result;
    if (plan_.kind == "stamp_freeze" && stamp <= 0)
    {
      close("aborted_invalid_stamp", now);
      return result;
    }
    if (!affected_)
      frozen_ = stamp;
    ++affected_;
    result.suppress = plan_.kind == "dropout";
    result.freeze = !result.suppress;
    result.stamp_ns = frozen_;
    if (affected_ == 1)
      events_.push_back({"activated", now, epoch_, affected_, true});
    return result;
  }
  void finish(int64_t now, bool failed = false)
  {
    if (!closed_)
      close(failed ? "aborted_runtime" : "aborted_shutdown", now);
  }
  std::vector<Event> drain()
  {
    auto result = std::move(events_);
    events_.clear();
    return result;
  }

private:
  void close(const std::string &state, int64_t now)
  {
    closed_ = true;
    events_.push_back({state, now, epoch_, affected_, affected_ != 0});
  }
  Plan plan_;
  bool anchored_{false}, closed_{false};
  int64_t last_{0}, start_{0}, end_{0}, frozen_{0};
  uint64_t epoch_{0}, affected_{0};
  std::vector<Event> events_;
};
} // namespace fault_injection
