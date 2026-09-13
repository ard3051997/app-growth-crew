from unittest.mock import MagicMock, patch

import pytest

from app_manager.rollback_manager import RollbackManager


@pytest.fixture
def mock_clients():
    with (
        patch("app_manager.rollback_manager.PlayStoreClient") as mock_play,
        patch("app_manager.rollback_manager.RevenueCatClient") as mock_rc,
    ):
        play_instance = MagicMock()
        rc_instance = MagicMock()
        mock_play.return_value = play_instance
        mock_rc.return_value = rc_instance

        yield play_instance, rc_instance


@pytest.mark.asyncio
async def test_capture_snapshot_aso(mock_clients):
    play_instance, _rc_instance = mock_clients

    mock_listing = MagicMock()
    mock_listing.title = "Old Title"
    mock_listing.short_description = "Old Short"
    mock_listing.full_description = "Old Full"
    mock_listing.video = "http://video"
    play_instance.get_listing.return_value = mock_listing

    manager = RollbackManager()
    snapshot = await manager.capture_snapshot(
        experiment_type="aso_metadata",
        app_package="com.example.app",
        args={"language": "en-US", "title": "New Title"},
    )

    play_instance.get_listing.assert_called_once_with(
        package_name="com.example.app", language="en-US"
    )
    assert snapshot == {
        "language": "en-US",
        "title": "Old Title",
        "short_description": "Old Short",
        "full_description": "Old Full",
        "video": "http://video",
    }


@pytest.mark.asyncio
async def test_execute_rollback_aso(mock_clients):
    play_instance, _rc_instance = mock_clients

    mock_result = MagicMock()
    mock_result.success = True
    play_instance.update_listing.return_value = mock_result

    manager = RollbackManager()
    snapshot = {
        "language": "en-US",
        "title": "Old Title",
        "short_description": "Old Short",
        "full_description": "Old Full",
        "video": "http://video",
    }

    success = await manager.execute_rollback(
        experiment_type="aso_metadata", app_package="com.example.app", snapshot_before=snapshot
    )

    play_instance.update_listing.assert_called_once_with(
        package_name="com.example.app",
        language="en-US",
        title="Old Title",
        short_description="Old Short",
        full_description="Old Full",
        video="http://video",
    )
    assert success is True
