from unittest.mock import patch

import pytest
import requests
import responses

from src.scripts.healthcheck import default_url, probe


URL = "http://localhost:9010/healthcheck"


@pytest.mark.unit
class TestDefaultUrl:
    def test_default_url__port_not_set__uses_default_port(self, monkeypatch):
        monkeypatch.delenv("HEALTHCHECK_SERVER_PORT", raising=False)

        assert default_url() == URL

    def test_default_url__port_set__uses_it(self, monkeypatch):
        monkeypatch.setenv("HEALTHCHECK_SERVER_PORT", "9999")

        assert default_url() == "http://localhost:9999/healthcheck"


@pytest.mark.unit
class TestProbe:
    @responses.activate
    def test_probe__status_200__returns_zero(self, capsys):
        responses.add(responses.GET, URL, status=200)

        result = probe(URL)

        assert result == 0
        assert capsys.readouterr().err == ""

    @responses.activate
    def test_probe__status_204__returns_zero(self):
        responses.add(responses.GET, URL, status=204)

        result = probe(URL)

        assert result == 0

    @responses.activate
    def test_probe__status_503__returns_one_and_prints_reason(self, capsys):
        responses.add(responses.GET, URL, status=503)

        result = probe(URL)

        assert result == 1
        assert "unexpected status 503" in capsys.readouterr().err

    @responses.activate
    def test_probe__status_404__returns_one(self):
        responses.add(responses.GET, URL, status=404)

        result = probe(URL)

        assert result == 1

    @responses.activate
    def test_probe__redirect_to_healthy_page__returns_one_without_following(self, capsys):
        target = "http://localhost:9010/other"
        responses.add(responses.GET, URL, status=302, headers={"Location": target})
        responses.add(responses.GET, target, status=200)

        result = probe(URL)

        assert result == 1
        assert "unexpected status 302" in capsys.readouterr().err
        assert len(responses.calls) == 1

    @responses.activate
    def test_probe__connection_error__returns_one_and_prints_reason(self, capsys):
        responses.add(responses.GET, URL, body=requests.ConnectionError("Connection refused"))

        result = probe(URL)

        assert result == 1
        assert "Healthcheck failed" in capsys.readouterr().err

    @responses.activate
    def test_probe__timeout__returns_one_and_prints_reason(self, capsys):
        responses.add(responses.GET, URL, body=requests.Timeout("Read timed out"))

        result = probe(URL)

        assert result == 1
        assert "Healthcheck failed" in capsys.readouterr().err

    def test_probe__custom_timeout__passes_it_to_request(self):
        with patch("src.scripts.healthcheck.requests.get") as get_mock:
            get_mock.return_value.status_code = 200

            result = probe(URL, timeout=7.5)

        assert result == 0
        get_mock.assert_called_once_with(URL, timeout=7.5, allow_redirects=False)
