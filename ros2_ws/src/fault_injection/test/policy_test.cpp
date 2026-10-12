#include "fault_injection/policy.hpp"
#include <gtest/gtest.h>
using fault_injection::Plan;
using fault_injection::Policy;
Plan plan(const std::string &kind = "dropout") { return {"experiment", "trial", kind, 10, 20}; }
TEST(FaultPolicy, BoundedDropoutAndExpiry)
{
  Policy policy(plan());
  EXPECT_FALSE(policy.sample(0, 1).suppress);
  EXPECT_FALSE(policy.sample(100, 100).suppress);
  EXPECT_FALSE(policy.sample(109, 109).suppress);
  EXPECT_TRUE(policy.sample(110, 110).suppress);
  EXPECT_TRUE(policy.sample(110, 110).suppress); // paused time stays active
  EXPECT_TRUE(policy.sample(129, 129).suppress);
  EXPECT_FALSE(policy.sample(130, 130).suppress);
  auto events = policy.drain();
  ASSERT_EQ(events.size(), 2u);
  EXPECT_EQ(events[0].state, "activated");
  EXPECT_EQ(events[0].ros_ns, 110);
  EXPECT_EQ(events[1].state, "ended");
  EXPECT_EQ(events[1].affected, 3u);
  policy.finish(140);
  EXPECT_TRUE(policy.drain().empty());
}
TEST(FaultPolicy, FreezeAndRegressionCannotRearm)
{
  Policy policy(plan("stamp_freeze"));
  policy.tick(100);
  EXPECT_EQ(policy.sample(110, 77).stamp_ns, 77);
  EXPECT_EQ(policy.sample(120, 88).stamp_ns, 77);
  EXPECT_FALSE(policy.sample(1, 1).freeze);
  EXPECT_FALSE(policy.sample(110, 110).freeze);
  auto events = policy.drain();
  ASSERT_EQ(events.size(), 2u);
  EXPECT_EQ(events[1].state, "aborted_clock");
  EXPECT_EQ(events[1].epoch, 1u);
}
TEST(FaultPolicy, JumpNotificationSurvivesReturnToOriginalTime)
{
  Policy policy(plan());
  policy.tick(100);
  policy.tick(101, true);
  EXPECT_FALSE(policy.sample(115, 115).suppress);
  EXPECT_EQ(policy.drain()[0].state, "aborted_clock");
}
TEST(FaultPolicy, RequestedIsNotAppliedAndCleanupIsIdempotent)
{
  Policy policy(plan());
  policy.tick(100);
  policy.tick(131);
  auto events = policy.drain();
  ASSERT_EQ(events.size(), 1u);
  EXPECT_EQ(events[0].state, "expired_unapplied");
  EXPECT_FALSE(events[0].confirmed);
  Policy stopped(plan());
  stopped.finish(0);
  stopped.finish(1);
  EXPECT_EQ(stopped.drain().size(), 1u);
}
TEST(FaultPolicy, BadStampAbortsFreeze)
{
  Policy policy(plan("stamp_freeze"));
  policy.tick(100);
  EXPECT_FALSE(policy.sample(110, 0).freeze);
  EXPECT_EQ(policy.drain()[0].state, "aborted_invalid_stamp");
  EXPECT_FALSE(policy.sample(120, 120).freeze);
}
TEST(FaultPolicy, RejectUnsupportedAndInvalidPlans)
{
  for (const auto &kind : {"", "noise", "dropout,stamp_freeze"})
    EXPECT_THROW(Policy{plan(kind)}, std::invalid_argument);
  for (int field = 0; field < 6; ++field)
  {
    auto bad = plan();
    if (field == 0)
      bad.experiment_id = "";
    if (field == 1)
      bad.trial_id = "../escape";
    if (field == 2)
      bad.delay_ns = -1;
    if (field == 3)
      bad.delay_ns = 3600000000001LL;
    if (field == 4)
      bad.duration_ns = 0;
    if (field == 5)
      bad.duration_ns = 60000000001LL;
    EXPECT_THROW(Policy{bad}, std::invalid_argument);
  }
}
