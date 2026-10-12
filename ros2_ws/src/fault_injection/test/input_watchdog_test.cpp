#include "fault_injection/input_watchdog.hpp"
#include <gtest/gtest.h>

using fault_injection::InputWatchdog;
TEST(InputWatchdog, DisabledPreservesExistingRelay)
{
  InputWatchdog watch(0, 100, 10);
  EXPECT_FALSE(watch.enabled());
  EXPECT_EQ(watch.failure(1000000), nullptr);
}
TEST(InputWatchdog, StartupAndAcquiredSilenceHaveSeparateDeadlines)
{
  InputWatchdog watch(100, 1000, 10);
  EXPECT_EQ(watch.failure(1010), nullptr);
  EXPECT_STREQ(watch.failure(1011), "upstream_scan_startup_timeout");
  watch.observe(500);
  EXPECT_EQ(watch.failure(600), nullptr);
  EXPECT_STREQ(watch.failure(601), "upstream_scan_timeout");
}
TEST(InputWatchdog, IncomingSamplesStayLiveEvenWhenOutputIsSuppressedOrRosClockPaused)
{
  InputWatchdog watch(100, 1000, 10);
  for (int64_t now = 20; now < 2000; now += 20)
  {
    watch.observe(now);
    EXPECT_EQ(watch.failure(now + 20), nullptr);
  }
}
TEST(InputWatchdog, MonotonicClockAndBounds)
{
  InputWatchdog watch(100, 1000, 10);
  watch.observe(200);
  EXPECT_NE(watch.failure(199), nullptr);
  EXPECT_THROW(InputWatchdog(-1, 100, 0), std::invalid_argument);
  EXPECT_THROW(InputWatchdog(100, 0, 0), std::invalid_argument);
}
