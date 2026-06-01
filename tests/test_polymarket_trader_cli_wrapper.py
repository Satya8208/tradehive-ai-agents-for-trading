import subprocess

from src.agents.polymarket_trader.cli_wrapper import PolymarketCLI
from src.agents.polymarket_trader.config import get_polymarket_cli_config


def test_extract_json_tolerates_codeblock_and_raw_payloads():
    payload = '{"markets":[1,2,3]}'
    parsed, parse_error = PolymarketCLI._extract_json(payload)
    assert parse_error is None
    assert parsed == {"markets": [1, 2, 3]}

    payload_with_noise = "INFO ping\n```\n{\"status\":\"ok\",\"value\":123}\n```\nDONE"
    parsed, parse_error = PolymarketCLI._extract_json(payload_with_noise)
    assert parse_error is None
    assert parsed == {"status": "ok", "value": 123}

    parsed, parse_error = PolymarketCLI._extract_json("not-json-at-all")
    assert parsed is None
    assert parse_error == "No JSON payload found"


def test_execute_retries_retryable_error_and_returns_parsed_payload(monkeypatch):
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_retry_count=1,
        cli_retry_backoff_seconds=0,
        cli_timeout_seconds=2,
    )
    cli = PolymarketCLI(cfg)
    monkeypatch.setattr(cli, "_cli_available", True)

    call_count = {"n": 0}

    def fake_run(cmd, capture_output=True, text=True, timeout=2):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return subprocess.CompletedProcess(cmd, 503, "", "temporary service unavailable")
        return subprocess.CompletedProcess(cmd, 0, '{"ok":true}', "")

    monkeypatch.setattr("src.agents.polymarket_trader.cli_wrapper.subprocess.run", fake_run)
    result = cli._execute(["markets", "list"], use_json=True)

    assert result.success is True
    assert result.payload == {"ok": True}
    assert result.error is None
    assert call_count["n"] == 2


def test_execute_classifies_bad_json_after_retries(monkeypatch):
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_retry_count=0,
        cli_retry_backoff_seconds=0,
        cli_timeout_seconds=2,
    )
    cli = PolymarketCLI(cfg)
    monkeypatch.setattr(cli, "_cli_available", True)
    monkeypatch.setattr(
        "src.agents.polymarket_trader.cli_wrapper.subprocess.run",
        lambda cmd, capture_output=True, text=True, timeout=2: subprocess.CompletedProcess(
            cmd, 0, "broken-json-@@@", ""
        ),
    )

    result = cli._execute(["markets", "list"], use_json=True)
    assert result.success is False
    assert result.error_code == "bad_json"


def test_execute_classifies_timeout(monkeypatch):
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_retry_count=0,
        cli_retry_backoff_seconds=0,
        cli_timeout_seconds=2,
    )
    cli = PolymarketCLI(cfg)
    monkeypatch.setattr(cli, "_cli_available", True)

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="timeout", timeout=2)

    monkeypatch.setattr("src.agents.polymarket_trader.cli_wrapper.subprocess.run", fake_run)
    result = cli._execute(["markets", "list"], use_json=True)

    assert result.success is False
    assert result.error_code == "timeout"


def test_to_token_normalization_handles_hex_whitespace_and_noise():
    cfg = get_polymarket_cli_config(use_direct_api=False)
    cli = PolymarketCLI(cfg)

    assert cli._to_token("0x64") == "100"
    assert cli._to_token("  0X64  ") == "100"
    assert cli._to_token("100") == "100"
    assert cli._to_token("12.34") == "12"
    assert cli._to_token("bad-id") == "bad-id"


def test_direct_limit_order_honors_requested_order_type():
    cfg = get_polymarket_cli_config(use_direct_api=False, cli_binary="polymarket-unavailable")
    cli = PolymarketCLI(cfg)

    class FakeClobClient:
        def __init__(self):
            self.created_order = None
            self.posted_order_type = None

        def create_order(self, order_args, options=None):
            self.created_order = order_args
            return {"signed": True}

        def post_order(self, order, orderType="GTC", post_only=False):
            self.posted_order_type = orderType
            return {"orderID": "order-1", "posted": order}

    fake_client = FakeClobClient()
    cli._clob_client = fake_client

    result = cli.create_limit_order(
        token_id="123",
        side="buy",
        price=0.42,
        size=7.0,
        order_type="FOK",
    )

    assert result["orderID"] == "order-1"
    assert fake_client.created_order.token_id == "123"
    assert fake_client.created_order.price == 0.42
    assert fake_client.created_order.size == 7.0
    assert str(fake_client.posted_order_type) == "FOK"


def test_execute_classifies_non_file_not_found_osexception_as_cli_unavailable(monkeypatch):
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_binary="polymarket-invalid",
        cli_retry_count=0,
        cli_timeout_seconds=1,
    )

    def fake_run(*_args, **_kwargs):
        raise OSError(193, "Invalid image", "polymarket-invalid")

    monkeypatch.setattr("src.agents.polymarket_trader.cli_wrapper.subprocess.run", fake_run)
    cli = PolymarketCLI(cfg)

    # Force an execution attempt despite init-time availability check.
    cli._cli_available = True
    result = cli._execute(["markets", "list"], use_json=True)
    assert result.success is False
    assert result.error_code == "cli_unavailable"


def test_status_reflects_cli_unavailable_when_binary_fails():
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_binary="polymarket-unavailable",
        cli_retry_count=0,
    )
    cli = PolymarketCLI(cfg)
    status = cli.get_health_status()

    assert status["cli_available"] is False
    assert status["cli_status_ok"] is False
    assert status["wallet_configured"] is False
    assert status["balance_read_ok"] is False
    assert "transport_not_ready" in status["permission_failures"]


def test_constructor_handles_non_file_not_found_osexception_as_cli_unavailable(monkeypatch):
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_binary="polymarket-invalid",
        cli_retry_count=0,
        cli_timeout_seconds=1,
    )

    def fake_run(*_args, **_kwargs):
        raise OSError(193, "The filename or extension is too long", "polymarket-invalid")

    monkeypatch.setattr("src.agents.polymarket_trader.cli_wrapper.subprocess.run", fake_run)
    cli = PolymarketCLI(cfg)

    assert cli.cli_available is False
    assert cli._cli_binary_check_error is not None
    status = cli.get_health_status()
    assert status["cli_status_ok"] is False
    assert status["cli_available"] is False


def test_search_markets_uses_gamma_catalog_fallback_without_cli(monkeypatch):
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_binary="polymarket-unavailable",
        cli_retry_count=0,
    )
    cli = PolymarketCLI(cfg)

    monkeypatch.setattr(
        cli,
        "_gamma_active_market_catalog",
        lambda limit=300: [
            {
                "conditionId": "m1",
                "question": "Ethereum Up or Down - April 15, 9:10AM-9:15AM ET",
                "slug": "eth-updown-5m",
                "description": "ETH intraday market",
                "active": True,
                "acceptingOrders": True,
                "liquidity": "12000",
            },
            {
                "conditionId": "m2",
                "question": "Russia-Ukraine Ceasefire before GTA VI?",
                "slug": "gta-vi-ceasefire",
                "active": True,
                "acceptingOrders": True,
            },
        ],
    )

    payload = cli.search_markets("ethereum up or down", limit=5)
    assert isinstance(payload, list)
    assert payload[0]["conditionId"] == "m1"
    assert all(item["conditionId"] != "m2" for item in payload)


def test_search_markets_matches_event_tagged_crypto_catalog_entries(monkeypatch):
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_binary="polymarket-unavailable",
        cli_retry_count=0,
    )
    cli = PolymarketCLI(cfg)

    monkeypatch.setattr(
        cli,
        "_gamma_active_market_catalog",
        lambda limit=300: [
            {
                "conditionId": "meta-1",
                "question": "Will MetaMask launch a token by June 30?",
                "slug": "will-metamask-launch-a-token-by-june-30",
                "eventTitle": "Will MetaMask launch a token by ___ ?",
                "eventTags": [{"slug": "crypto", "label": "Crypto"}],
                "active": True,
                "acceptingOrders": True,
                "liquidity": "8500",
            },
            {
                "conditionId": "generic-1",
                "question": "Will it rain tomorrow?",
                "slug": "will-it-rain-tomorrow",
                "active": True,
                "acceptingOrders": True,
            },
        ],
    )

    payload = cli.search_markets("crypto", limit=5)
    assert isinstance(payload, list)
    assert payload[0]["conditionId"] == "meta-1"
    assert all(item["conditionId"] != "generic-1" for item in payload)


def test_search_markets_reuses_prepared_catalog_index(monkeypatch):
    cfg = get_polymarket_cli_config(
        use_direct_api=False,
        cli_binary="polymarket-unavailable",
        cli_retry_count=0,
    )
    cli = PolymarketCLI(cfg)
    catalog = [
        {
            "conditionId": "m1",
            "question": "Ethereum Up or Down this hour?",
            "slug": "eth-updown-hour",
            "active": True,
            "acceptingOrders": True,
            "liquidity": "12000",
            "volume24hr": "8000",
        },
        {
            "conditionId": "m2",
            "question": "Bitcoin above 100000 this week?",
            "slug": "btc-above-week",
            "active": True,
            "acceptingOrders": True,
            "liquidity": "9000",
            "volume24hr": "6000",
        },
    ]
    calls = {"count": 0}
    original = cli._gamma_market_search_text

    def counting_search_text(market):
        calls["count"] += 1
        return original(market)

    monkeypatch.setattr(cli, "_gamma_active_market_catalog", lambda limit=300: catalog)
    monkeypatch.setattr(cli, "_gamma_market_search_text", counting_search_text)

    first = cli.search_markets("ethereum", limit=5)
    second = cli.search_markets("eth price", limit=5)

    assert isinstance(first, list)
    assert isinstance(second, list)
    assert calls["count"] == len(catalog)


def test_get_wallet_address_uses_direct_address_when_cli_unavailable():
    cfg = get_polymarket_cli_config(use_direct_api=False, cli_binary="polymarket-unavailable")
    cli = PolymarketCLI(cfg)
    cli._eoa_address = "0x1234567890abcdef1234567890abcdef12345678"

    assert cli.get_wallet_address() == "0x1234567890abcdef1234567890abcdef12345678"
