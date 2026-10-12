#include "fault_injection/owned_policy.hpp"
#include <gtest/gtest.h>
using fault_injection::OwnedPolicy;
using fault_injection::Plan;
const std::string mission(32, 'a'), nav(32, 'b'), other(32, 'c');
OwnedPolicy owned(const std::string &kind = "dropout")
{
  return OwnedPolicy(Plan{"experiment", "trial", kind, 10, 20}, 0, 1000, 50);
}
void start(OwnedPolicy &p)
{
  ASSERT_TRUE(p.arm(mission, 100, 1));
  ASSERT_TRUE(p.bind(mission, nav, 100, 2));
  p.status(nav, 2, 100, 3);
  p.feedback(nav, 100, 4);
}
TEST(OwnedFault, AcceptanceAndExecutingAloneNeverApply)
{
  auto p = owned();
  EXPECT_FALSE(p.sample(100, 100, 1).suppress);
  ASSERT_TRUE(p.arm(mission, 100, 2));
  EXPECT_FALSE(p.sample(200, 200, 3).suppress);
  ASSERT_TRUE(p.bind(mission, nav, 200, 4));
  p.status(nav, 1, 200, 5);
  p.feedback(nav, 200, 6);
  EXPECT_FALSE(p.sample(200, 200, 7).suppress);
  p.status(nav, 2, 200, 8);
  EXPECT_FALSE(p.sample(209, 209, 9).suppress);
  EXPECT_TRUE(p.sample(210, 210, 10).suppress);
  auto q = owned();
  ASSERT_TRUE(q.arm(mission, 100, 1));
  ASSERT_TRUE(q.bind(mission, nav, 100, 2));
  q.status(nav, 2, 100, 3);
  EXPECT_FALSE(q.sample(500, 500, 4).suppress);
}
TEST(OwnedFault, CrossTrialDuplicateLateAndMultiWaypointIsolation)
{
  auto p = owned();
  EXPECT_FALSE(p.bind(mission, nav, 100, 1));
  ASSERT_TRUE(p.arm(mission, 100, 2));
  EXPECT_FALSE(p.arm(mission, 100, 3));
  EXPECT_FALSE(p.bind(other, nav, 100, 3));
  ASSERT_TRUE(p.bind(mission, nav, 100, 4));
  EXPECT_FALSE(p.bind(mission, other, 100, 5));
  p.status(other, 2, 100, 6);
  p.feedback(other, 100, 7);
  EXPECT_FALSE(p.sample(200, 200, 8).suppress);
  p.stop(200, 9, "cancel");
  p.status(nav, 2, 200, 10);
  p.feedback(nav, 200, 11);
  EXPECT_FALSE(p.sample(220, 220, 12).suppress);
  EXPECT_FALSE(p.bind(mission, other, 220, 13));
}
TEST(OwnedFault, CancelAtEveryStageIsIrreversible)
{
  for (int stage = 0; stage < 4; ++stage)
  {
    auto p = owned();
    if (stage >= 1)
      ASSERT_TRUE(p.arm(mission, 100, 1));
    if (stage >= 2)
      ASSERT_TRUE(p.bind(mission, nav, 100, 2));
    if (stage >= 3)
    {
      p.status(nav, 2, 100, 3);
      p.feedback(nav, 100, 4);
      EXPECT_TRUE(p.sample(110, 110, 5).suppress);
    }
    p.stop(110, 6, "cancel");
    EXPECT_FALSE(p.sample(120, 120, 7).suppress);
    EXPECT_FALSE(p.arm(mission, 120, 8));
    EXPECT_FALSE(p.verified());
    p.forwarded(120, 120);
    EXPECT_FALSE(p.verified());
    p.forwarded(121, 121);
    EXPECT_TRUE(p.verified());
  }
}
TEST(OwnedFault, WallDeadlineStopsPausedFaultAndUncertaintyLatches)
{
  auto p = owned();
  start(p);
  EXPECT_TRUE(p.sample(110, 110, 10).suppress);
  EXPECT_TRUE(p.sample(110, 110, 999).suppress);
  EXPECT_FALSE(p.sample(110, 110, 1000).suppress);
  p.tick(110, 1050);
  EXPECT_EQ(p.state(), "recovery_uncertain");
  p.forwarded(111, 111);
  p.forwarded(112, 112);
  EXPECT_FALSE(p.verified());
}
TEST(OwnedFault, ClockResetRejectTerminalAndShutdownCannotRearm)
{
  for (int scenario = 0; scenario < 4; ++scenario)
  {
    auto p = owned();
    start(p);
    if (scenario == 0)
      p.tick(1, 5);
    if (scenario == 1)
      p.status(nav, 6, 100, 5);
    if (scenario == 2)
      p.status(nav, 3, 100, 5);
    if (scenario == 3)
      p.stop(100, 5, "shutdown");
    EXPECT_FALSE(p.sample(111, 111, 6).suppress);
    EXPECT_FALSE(p.arm(mission, 111, 7));
  }
}
TEST(OwnedFault, ExpiryAcknowledgementEffectAndRecoveryAreDistinct)
{
  auto p = owned("stamp_freeze");
  start(p);
  p.tick(110, 5);
  EXPECT_EQ(p.state(), "activation_acknowledged");
  EXPECT_FALSE(p.verified());
  EXPECT_TRUE(p.sample(111, 77, 6).freeze);
  EXPECT_EQ(p.state(), "effect_observed");
  EXPECT_FALSE(p.sample(130, 130, 7).freeze);
  EXPECT_EQ(p.state(), "recovery_requested");
  p.forwarded(131, 131);
  p.forwarded(132, 132);
  EXPECT_TRUE(p.verified());
  auto events = p.drain();
  EXPECT_EQ(events[0].state, "armed");
  EXPECT_EQ(events[2].state, "execution_started");
  EXPECT_EQ(events[3].state, "activation_acknowledged");
  EXPECT_EQ(events[4].state, "effect_observed");
  EXPECT_TRUE(events[4].confirmed);
  EXPECT_EQ(events.back().state, "recovery_verified");
  EXPECT_FALSE(events.back().confirmed);
}
TEST(OwnedFault, InvalidConfigurationAndUuid)
{
  EXPECT_THROW(OwnedPolicy(Plan{"e", "t", "dropout", 0, 10}, 0, 0, 1), std::invalid_argument);
  EXPECT_FALSE(OwnedPolicy::uuid(std::string(32, '0')));
  EXPECT_FALSE(OwnedPolicy::uuid("bad"));
  auto p = owned();
  EXPECT_FALSE(p.arm("bad", 100, 1));
  EXPECT_FALSE(p.arm(mission, 0, 1));
}

TEST(OwnedFault, StaleRepeatedOrFutureStampsCannotVerifyRestoration)
{
  auto p = owned();
  start(p);
  p.stop(1000000000LL, 5, "cancel");
  p.forwarded(1000000000LL, 1);
  p.forwarded(1000000000LL, 2);
  p.forwarded(1000000000LL, 1000000001LL);
  EXPECT_FALSE(p.verified());
  p.forwarded(1000000000LL, 1000000000LL);
  p.forwarded(1000000000LL, 1000000000LL);
  EXPECT_FALSE(p.verified());
  p.forwarded(1000000001LL, 1000000001LL);
  EXPECT_FALSE(p.verified());
  p.forwarded(1000000002LL, 1000000002LL);
  EXPECT_TRUE(p.verified());
}

TEST(OwnedFault, CancelEvidenceCountsEveryAffectedSample)
{
  auto p = owned();
  start(p);
  EXPECT_TRUE(p.sample(110, 110, 5).suppress);
  EXPECT_TRUE(p.sample(111, 111, 6).suppress);
  EXPECT_TRUE(p.sample(112, 112, 7).suppress);
  p.stop(113, 8, "cancel");
  auto events = p.drain();
  EXPECT_EQ(events.back().affected, 3u);
}
