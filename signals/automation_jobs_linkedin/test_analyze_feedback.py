from analyze_feedback import feedback_metrics


def test_feedback_metrics_calculate_quality_and_funnel():
    rows = [
        {"fit_rating": "5", "applied": "yes", "response": "yes", "interview": "true", "won": "1"},
        {"fit_rating": "4", "applied": "x", "response": "", "interview": "", "won": ""},
        {"fit_rating": "2", "rejection_reason": "US only"},
        {"fit_rating": "bad", "rejection_reason": "US only"},
    ]
    result = feedback_metrics(rows)
    assert result["rated_jobs"] == 3
    assert result["precision_at_4_plus"] == 0.6667
    assert result["applied"] == 2
    assert result["response_rate"] == 0.5
    assert result["top_rejection_reasons"][0] == {"reason": "US only", "count": 2}


def test_feedback_metrics_handle_empty_feedback():
    result = feedback_metrics([])
    assert result["precision_at_4_plus"] is None
    assert result["response_rate"] is None
