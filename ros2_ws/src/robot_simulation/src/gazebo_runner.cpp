#include <cerrno>
#include <csignal>
#include <filesystem>
#include <iostream>
#include <pthread.h>
#include <stdexcept>
#include <string>

#include <gz/sim/Server.hh>
#include <gz/sim/ServerConfig.hh>

int main(int argc, char **argv)
{
  try
  {
    if (argc != 3 || (std::string(argv[2]) != "true" && std::string(argv[2]) != "false"))
    {
      throw std::invalid_argument("usage: gazebo_runner WORLD.sdf HEADLESS(true|false)");
    }
    if (!std::filesystem::is_regular_file(argv[1]))
    {
      throw std::invalid_argument("world must be an existing SDF file");
    }
    sigset_t signals;
    sigemptyset(&signals);
    sigaddset(&signals, SIGINT);
    sigaddset(&signals, SIGTERM);
    if (pthread_sigmask(SIG_BLOCK, &signals, nullptr) != 0)
    {
      throw std::runtime_error("cannot block shutdown signals before starting Gazebo");
    }
    // Workers inherit this mask. Never run blocking Gazebo cleanup inside its
    // asynchronous signal handler: it can interrupt a held allocator lock.
    gz::sim::ServerConfig config;
    config.SetSdfFile(std::filesystem::absolute(argv[1]).string());
    config.SetHeadlessRendering(std::string(argv[2]) == "true");
    config.SetBehaviorOnSdfErrors(gz::sim::ServerConfig::SdfErrorBehavior::EXIT_IMMEDIATELY);
    gz::sim::Server server(config);
    if (!server.EntityCount().has_value() || !server.Run(false, 0, false))
    {
      throw std::runtime_error("Gazebo could not start the configured world");
    }
    std::cout << "Gazebo server running; shutdown signals handled synchronously" << std::endl;
    const timespec interval{0, 100000000};
    while (server.Running())
    {
      const int received = sigtimedwait(&signals, nullptr, &interval);
      if (received == SIGINT || received == SIGTERM)
      {
        server.Stop();
        break;
      }
      if (received < 0 && errno != EAGAIN && errno != EINTR)
      {
        server.Stop();
        throw std::runtime_error("sigtimedwait failed");
      }
    }
    // Keep signals blocked until after the server and all plugins are destroyed.
    server.Stop();
    return 0;
  }
  catch (const std::exception &error)
  {
    std::cerr << "gazebo_runner: " << error.what() << std::endl;
    return 1;
  }
}
