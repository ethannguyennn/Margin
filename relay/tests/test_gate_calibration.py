import pytest

from eval.tune_gate import calibration


def test_calibration_protects_answers_and_ambiguities():
    samples = [{'best_sim': 0.8, 'best_rrf': 0.03, 'protected': True},
               {'best_sim': 0.4, 'best_rrf': 0.02, 'protected': True},
               {'best_sim': 0.1, 'best_rrf': 0.005, 'protected': False}]
    report = calibration(samples)
    assert report['protected_false_refusals'] == 0
    assert report['cheap_refusals'] == report['refusal_candidates'] == 1


def test_overlap_does_not_invent_confidence_or_refuse_answers():
    samples = [{'best_sim': 0.8, 'best_rrf': 0.03, 'protected': True},
               {'best_sim': 0.8, 'best_rrf': 0.03, 'protected': False}]
    assert calibration(samples)['cheap_refusals'] == 0


@pytest.mark.parametrize('samples', [[], [{'best_sim': 0.8, 'best_rrf': 0.03, 'protected': True}]])
def test_one_sided_calibration_is_rejected(samples):
    with pytest.raises(ValueError):
        calibration(samples)
