#pragma once
#include "fault_injection/policy.hpp"

namespace fault_injection
{
// Pure one-shot owned policy. Caller supplies steady wall time and trusted UUID evidence.
class OwnedPolicy
{
public:
  OwnedPolicy(Plan plan, int64_t wall, int64_t lease, int64_t recovery)
      : plan_(plan), policy_(plan), deadline_(wall + lease), recovery_limit_(recovery)
  {
    if (lease <= 0 || lease > 120000000000LL || recovery <= 0 || recovery > 30000000000LL)
      throw std::invalid_argument("wall lease (0,120] s and recovery (0,30] s required");
  }
  static bool uuid(const std::string &id)
  {
    return id.size() == 32 && id.find_first_not_of("0123456789abcdef") == std::string::npos &&
           id.find_first_not_of('0') != std::string::npos;
  }
  bool arm(const std::string &mission, int64_t now, int64_t wall)
  {
    tick(now, wall);
    if (state_ != "pending" || now <= 0 || !uuid(mission))
      return false;
    mission_ = mission;
    state_ = "armed";
    event("armed", now);
    return true;
  }
  bool bind(const std::string &mission, const std::string &nav, int64_t now, int64_t wall)
  {
    tick(now, wall);
    if (state_ != "armed" || mission != mission_ || !nav_.empty() || !uuid(nav))
      return false;
    nav_ = nav;
    event("nav_accepted", now);
    return true;
  }
  void status(const std::string &nav, int status, int64_t now, int64_t wall)
  {
    tick(now, wall);
    if (nav_.empty() || nav != nav_ || closed_)
      return;
    if (status >= 3 && status <= 6) // CANCELING or any terminal status
    {
      stop(now, wall, "nav_terminal_or_canceling");
      return;
    }
    executing_ = status == 2;
    gate(now, wall);
  }
  void feedback(const std::string &nav, int64_t now, int64_t wall)
  {
    tick(now, wall);
    if (nav_.empty() || nav != nav_ || closed_)
      return;
    feedback_ = true;
    gate(now, wall);
  }
  void tick(int64_t now, int64_t wall, bool jumped = false)
  {
    if (jumped || (last_ > 0 && now < last_))
    {
      ++epoch_;
      stop(now, wall, "clock_reset");
    }
    last_ = now;
    if (!closed_ && wall >= deadline_)
      stop(now, wall, "wall_lease_expired");
    if (started_ && !closed_)
    {
      policy_.tick(now);
      collect(now, wall);
      if (!closed_ && now >= origin_ + plan_.delay_ns && !acknowledged_)
      {
        acknowledged_ = true;
        state_ = "activation_acknowledged";
        event(state_, now);
      }
    }
    if (closed_ && !verified_ && !uncertain_ && wall >= recovery_deadline_)
    {
      uncertain_ = true;
      state_ = "recovery_uncertain";
      event(state_, now);
    }
  }
  Decision sample(int64_t now, int64_t stamp, int64_t wall, bool jumped = false)
  {
    tick(now, wall, jumped);
    if (!started_ || closed_)
      return {};
    auto result = policy_.sample(now, stamp);
    if (result.suppress || result.freeze)
      ++affected_;
    collect(now, wall);
    return result;
  }
  // Call only AFTER unchanged scan was successfully published locally.
  void forwarded(int64_t now, int64_t stamp)
  {
    if (!closed_ || verified_ || uncertain_ || stamp <= 0 || now <= 0 || stamp > now ||
        now - stamp > 500000000LL)
      return;
    if (stamp > restored_stamp_)
      ++restored_count_;
    else
      restored_count_ = 0;
    restored_stamp_ = stamp;
    if (restored_count_ >= 2)
    {
      verified_ = true;
      state_ = "recovery_verified";
      event(state_, now);
    }
  }
  void stop(int64_t now, int64_t wall, const std::string &reason)
  {
    if (closed_)
      return;
    closed_ = true;
    state_ = "recovery_requested";
    recovery_deadline_ = wall + recovery_limit_;
    event("stopped_" + reason, now);
    event(state_, now);
  }
  std::vector<Event> drain()
  {
    auto result = std::move(events_);
    events_.clear();
    return result;
  }
  const std::string &state() const { return state_; }
  const std::string &mission() const { return mission_; }
  const std::string &nav() const { return nav_; }
  bool verified() const { return verified_; }
  uint64_t epoch() const { return epoch_; }

private:
  void gate(int64_t now, int64_t wall)
  {
    if (!started_ && executing_ && feedback_ && now > 0)
    {
      started_ = true;
      origin_ = now;
      state_ = "execution_started";
      event(state_, now);
      tick(now, wall);
    }
  }
  void collect(int64_t now, int64_t wall)
  {
    for (auto event : policy_.drain())
    {
      if (event.state == "activated")
      {
        state_ = "effect_observed";
        this->event(state_, now);
      }
      else
      {
        affected_ = event.affected;
        stop(now, wall, event.state);
      }
    }
  }
  void event(const std::string &state, int64_t now)
  {
    events_.push_back({state, now, epoch_, affected_, state == "effect_observed"});
  }
  Plan plan_;
  Policy policy_;
  std::string state_{"pending"}, mission_, nav_;
  bool executing_{false}, feedback_{false}, started_{false}, closed_{false}, acknowledged_{false},
      verified_{false}, uncertain_{false};
  int64_t deadline_, recovery_limit_, recovery_deadline_{0}, last_{0}, origin_{0},
      restored_stamp_{0};
  uint64_t epoch_{0}, affected_{0}, restored_count_{0};
  std::vector<Event> events_;
};
} // namespace fault_injection
