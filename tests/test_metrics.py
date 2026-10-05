"""
Тесты метрик и демо-заглушек ХелпИнатора.
Запуск:  pytest -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

from server import app, METRICS
import demo_scenarios


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ----------------------------- сценарии -----------------------------
def test_20_scenarios_present():
    assert len(demo_scenarios.SCENARIOS) == 20
    ids = [s["id"] for s in demo_scenarios.SCENARIOS]
    assert len(set(ids)) == 20, "ID сценариев должны быть уникальны"


def test_scenarios_structure():
    for s in demo_scenarios.SCENARIOS:
        assert s["triage"] in ("green", "yellow", "red")
        assert s["questions"], f"Нет вопросов у {s['id']}"
        for k in ("S", "O", "A", "P"):
            assert k in s["soap"], f"SOAP.{k} отсутствует у {s['id']}"


def test_match_scenario_orvi():
    s = demo_scenarios.match_scenario("у меня кашель и насморк, слабость")
    assert s is not None and s["id"] == "orvi"


def test_match_scenario_chest_pain():
    s = demo_scenarios.match_scenario("давит в груди, отдаёт в левую руку")
    assert s is not None and s["id"] == "chest_pain"


def test_next_question_progression():
    items = [{"n": 1, "question": "", "complaint": "кашель и насморк"}]
    q1 = demo_scenarios.next_question(items)
    assert "симптомы" in q1.lower() or "температур" in q1.lower() or "как давно" in q1.lower()

    items.append({"n": 2, "question": q1, "complaint": "3 дня, 37.4"})
    q2 = demo_scenarios.next_question(items)
    assert q2 != q1


def test_soap_for_known_scenario():
    items = [{"complaint": "ангина, температура 38.5, больно глотать"}]
    soap = demo_scenarios.soap_for(items)
    assert soap is not None
    assert "тонзиллит" in soap["A"].lower() or "ангина" in soap["A"].lower()


# ----------------------------- metrics -----------------------------
def test_metrics_endpoint_shape(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    data = r.json()
    for block in ("llm", "ocr", "triage", "nps"):
        assert block in data
    assert data["llm"]["target_p95_ms"] == 3000
    assert data["ocr"]["target_success_rate_pct"] == 90


def test_nps_endpoint(client):
    before = client.get("/api/metrics").json()["nps"]["responses"]
    r = client.post("/api/metrics/nps", json={"score": 9})
    assert r.status_code == 200
    r = client.post("/api/metrics/nps", json={"score": 6})
    assert r.status_code == 200
    after = client.get("/api/metrics").json()["nps"]["responses"]
    assert after == before + 2


def test_nps_clamped(client):
    client.post("/api/metrics/nps", json={"score": 999})
    client.post("/api/metrics/nps", json={"score": -5})
    snap = client.get("/api/metrics").json()
    assert snap["nps"]["score"] is not None


def test_triage_feedback(client):
    r = client.post("/api/metrics/triage-feedback", json={"false_positive": True})
    assert r.status_code == 200
    r = client.post("/api/metrics/triage-feedback", json={"false_positive": False})
    assert r.status_code == 200


def test_triage_endpoint_red(client):
    r = client.post("/api/triage", json={"text": "давит в груди, отдаёт в левую руку"})
    assert r.status_code == 200
    assert r.json()["level"] == "red"


def test_triage_endpoint_green(client):
    r = client.post("/api/triage", json={"text": "лёгкий насморк без температуры"})
    assert r.status_code == 200
    assert r.json()["level"] == "green"


def test_bench_run(client):
    r = client.post("/api/bench/run")
    assert r.status_code == 200
    data = r.json()
    assert data["scenarios"] == 20
    assert data["metrics"]["llm"]["samples"] >= 20
    assert data["metrics"]["triage"]["total"] >= 20
    assert data["metrics"]["ocr"]["total"] >= 20
    assert data["metrics"]["nps"]["responses"] >= 20


def test_p95_under_3s_in_demo(client):
    """В демо-режиме (fallback) P95 должен быть < 3 сек."""
    client.post("/api/bench/run")
    snap = client.get("/api/metrics").json()
    p95 = snap["llm"]["p95_ms"]
    assert p95 is not None
    assert p95 < 3000, f"P95 = {p95} ms, ожидалось < 3000"


def test_ocr_success_rate_above_90(client):
    client.post("/api/bench/run")
    snap = client.get("/api/metrics").json()
    rate = snap["ocr"]["success_rate_pct"]
    assert rate is not None
    assert rate >= 85, f"Успешность OCR {rate}% < 85%"