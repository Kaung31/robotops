import asyncio
import time

from robotops_backend.models import ConnectionState, RuntimeMode
from robotops_backend.state import TelemetryStore


def test_initial_state_is_disconnected():
    assert TelemetryStore().latest().connection == ConnectionState.DISCONNECTED


def test_publish_marks_connected_and_preserves_mode():
    store = TelemetryStore(stale_after_seconds=10)
    store.publish(runtime_mode=RuntimeMode.SIM)
    snapshot = store.latest()
    assert snapshot.connection == ConnectionState.CONNECTED
    assert snapshot.runtime_mode == RuntimeMode.SIM


def test_snapshot_becomes_stale():
    store = TelemetryStore(stale_after_seconds=0.001)
    store.publish(runtime_mode=RuntimeMode.SIM)
    time.sleep(0.003)
    assert store.latest().connection == ConnectionState.STALE


def test_subscriber_receives_latest_then_update():
    async def scenario():
        store = TelemetryStore()
        stream = store.subscribe()
        first = await anext(stream)
        assert first.connection == ConnectionState.DISCONNECTED
        store.publish(runtime_mode=RuntimeMode.MOCK)
        second = await anext(stream)
        assert second.runtime_mode == RuntimeMode.MOCK
        await stream.aclose()

    asyncio.run(scenario())


def test_mark_disconnected_does_not_fake_freshness():
    store = TelemetryStore(stale_after_seconds=10)
    store.publish(runtime_mode=RuntimeMode.SIM)
    assert store.latest().connection == ConnectionState.CONNECTED
    store.mark_disconnected(RuntimeMode.SIM)
    snapshot = store.latest()
    assert snapshot.connection == ConnectionState.DISCONNECTED
    assert snapshot.runtime_mode == RuntimeMode.SIM


def test_subscriber_emits_stale_transition_without_new_ros_message():
    async def scenario():
        store = TelemetryStore(stale_after_seconds=0.01)
        store.publish(runtime_mode=RuntimeMode.SIM)
        stream = store.subscribe()
        first = await anext(stream)
        assert first.connection == ConnectionState.CONNECTED
        second = await asyncio.wait_for(anext(stream), timeout=0.2)
        assert second.connection == ConnectionState.STALE
        await stream.aclose()

    asyncio.run(scenario())
