"""测试造浪五力模型。"""
import pytest
from core.five_forces_model import (
    FiveForcesProfile, ForceDimension, ForceObservation,
    ForceDimensionState, build_default_five_forces_profile,
    FORCE_LABELS,
)


def test_build_default_profile():
    profile = build_default_five_forces_profile("learner_001")
    assert profile.learner_id == "learner_001"
    assert len(profile.dimensions) == 5
    for dim in ForceDimension:
        assert dim.value in profile.dimensions
    assert profile.get_score(ForceDimension.CURIOSITY) == 25.0


def test_record_observation_updates_score():
    profile = build_default_five_forces_profile("learner_001")
    obs = ForceObservation(
        dimension=ForceDimension.CURIOSITY,
        score=80.0,
        evidence="主动问了5个关于蜗牛的问题",
        context="森林徒步",
        observer="张导师",
    )
    profile.record_observation(obs)
    # 25 * 0.7 + 80 * 0.3 = 17.5 + 24 = 41.5
    assert 41.0 <= profile.get_score(ForceDimension.CURIOSITY) <= 42.0
    assert len(profile.observations) == 1


def test_multiple_observations_converge():
    profile = build_default_five_forces_profile("learner_001")
    for _ in range(10):
        profile.record_observation(ForceObservation(
            dimension=ForceDimension.RESILIENCE,
            score=90.0,
            evidence="坚持完成挑战",
        ))
    assert profile.get_score(ForceDimension.RESILIENCE) > 70.0


def test_get_level():
    profile = build_default_five_forces_profile("learner_001")
    assert profile.get_level(ForceDimension.CURIOSITY) == "萌芽期"

    profile.dimensions["creativity"] = ForceDimensionState(
        dimension=ForceDimension.CREATIVITY, current_score=80.0,
    )
    assert profile.get_level(ForceDimension.CREATIVITY) == "绽放期"


def test_radar_data():
    profile = build_default_five_forces_profile("learner_001")
    radar = profile.get_radar_data()
    assert len(radar) == 5
    assert all(isinstance(v, float) for v in radar.values())


def test_summary():
    profile = build_default_five_forces_profile("learner_001")
    profile.record_observation(ForceObservation(
        dimension=ForceDimension.COLLABORATION,
        score=95.0,
        evidence="主动协调团队分工",
    ))
    summary = profile.get_summary()
    assert "top_strength" in summary
    assert "growth_area" in summary


def test_highlight_observations():
    profile = build_default_five_forces_profile("learner_001")
    for i, dim in enumerate(ForceDimension):
        profile.record_observation(ForceObservation(
            dimension=dim, score=50.0 + i * 10,
            evidence=f"观察{i}",
        ))
    highlights = profile.get_highlight_observations(limit=3)
    assert 1 <= len(highlights) <= 3
    scores = [h.score for h in highlights]
    assert scores == sorted(scores, reverse=True)


def test_force_labels_complete():
    for dim in ForceDimension:
        assert dim in FORCE_LABELS
        labels = FORCE_LABELS[dim]
        assert "name" in labels
        assert "icon" in labels
        assert "description" in labels
        assert "low_desc" in labels
        assert "mid_desc" in labels
        assert "high_desc" in labels


def test_dimension_growth_trajectory():
    profile = build_default_five_forces_profile("learner_001")
    profile.record_observation(ForceObservation(
        dimension=ForceDimension.CURIOSITY, score=40.0, evidence="第一次",
    ))
    profile.record_observation(ForceObservation(
        dimension=ForceDimension.CURIOSITY, score=60.0, evidence="第二次",
    ))
    trajectory = profile.get_dimension_growth(ForceDimension.CURIOSITY)
    assert len(trajectory) == 2
    assert trajectory[0]["score"] == 40.0
    assert trajectory[1]["score"] == 60.0
