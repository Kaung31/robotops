import pytest
from pydantic import ValidationError
from robotops_backend.models import MapSnapshot, ScanPoint


def test_map_dimensions_must_match_data():
    with pytest.raises(ValidationError):
        MapSnapshot(width=2, height=2, resolution=0.05, data=[0, 0, 0])


def test_non_empty_map_requires_positive_resolution():
    with pytest.raises(ValidationError):
        MapSnapshot(width=1, height=1, resolution=0.0, data=[0])


def test_scan_points_must_be_finite():
    with pytest.raises(ValidationError):
        ScanPoint(x=float("nan"), y=0.0)
