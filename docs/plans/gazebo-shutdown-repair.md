# Gazebo shutdown repair (2026-10-08)

## Evidence and goal

The M6 full run reproduced the pre-existing hang in `mapping_system` (Gazebo PID
170807). GDB captured the process after SIGINT, before launch escalated its signal.
Main thread: `SignalHandlerPrivate::OnSignal -> SensorsPrivate::Stop -> thread::join`,
with the interrupted stack inside `_int_malloc(main_arena)`. Sensor thread 170917:
`SensorsPrivate::RenderThread -> RenderUtil::Destroy -> Ogre2Scene::Destroy -> free`,
waiting on the same `main_arena` allocator lock. This is a signal-context deadlock,
not a slow recorder or a mission-specific branch. Debugging attachment may extend
teardown time, but these mutually blocked stacks identify a real lock cycle.
The complete local capture is `/tmp/robotops-gz-hang-170807.bt`.

## Narrow implementation

Add `robot_simulation/src/gazebo_runner.cpp`, linking the existing Gazebo Harmonic
Server API. Block SIGINT/SIGTERM before constructing the server (workers inherit
the mask), receive them synchronously with `sigtimedwait`, and invoke `Server::Stop`
from normal main-thread context. Preserve world, plugin path, unpaused operation,
headless-rendering option and the separate optional GUI. Keep signal masking in
force through server destruction. No upstream library patch, middleware change,
new package, extended kill timeout or relaxed shutdown assertion is involved.

Update simulation CMake/manifest and only its server launch command. Add tests for
invalid inputs, SIGINT/SIGTERM while rendered sensors are active, and inherited
thread masks. Re-run existing control/mapping/navigation/mission/experiment tests.

## Success criteria

Signals cannot interrupt Gazebo allocator/physics/render callbacks to perform
blocking cleanup. Sensor-enabled processes exit normally without force-kill; both
signal types are covered. All existing robot contracts and system assertions pass.
Preserve failed-run evidence and report validation limits; direct external `gz sim`
commands still use the upstream executable and are outside this adapter fix.

API inspected: installed Jazzy Harmonic headers and upstream
[Server implementation](https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/Server.cc).

## Focused verification

The native entry point compiled against installed Harmonic 8.11 with warnings
`-Wall -Wextra -Wpedantic`. Invalid/missing arguments fail explicitly. Rendered
LiDAR output was observed before each shutdown. Worker-thread signal masks were
checked via `/proc`; the main thread is excluded because Linux temporarily adjusts
its visible mask during synchronous `sigtimedwait`, not because shutdown runs in
an asynchronous handler.

`xvfb-run -a ctest --repeat until-fail:10 -R '^gazebo_shutdown$'
--output-on-failure` passed ten repetitions (20 sensor-enabled SIGINT/SIGTERM
cases) in 57.33 seconds. Existing process timeouts and failure assertions remain
unchanged. The wrapper does not make arbitrary upstream `gz sim` invocations safe;
repository sim bringup now selects the wrapper.

The failed pre-repair full run also had an independent Fast DDS/rmw action-response
timeout in `mission_system`: the server warned that the client would not receive
its acceptance response. This is not attributed to or claimed fixed by the
Gazebo shutdown repair. Its mission was canceled during test cleanup.
