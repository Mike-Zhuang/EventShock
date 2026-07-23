from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import createApp

OWNER = "factory-owner-0001"
OTHER_OWNER = "factory-owner-0002"
HEADERS = {"X-Session-ID": OWNER}


def test_factory_api_materializes_reviewable_pack_and_preserves_owner_boundary(
    tmp_path: Path,
) -> None:
    evidenceQuote = (
        "The exchange published a verified notice explaining that market-maker "
        "capacity was temporarily reduced during the public event."
    )
    rawText = " ".join([evidenceQuote] * 20) + " PRIVATE_RAW_TAIL_83b7f2"
    with TestClient(createApp(dataDir=tmp_path)) as client:
        catalog = client.get(
            "/api/v1/event-pack-factory/search-engines",
            headers=HEADERS,
        )
        assert catalog.status_code == 200
        assert {item["engine"] for item in catalog.json()["items"]} == {
            "search_std",
            "search_pro",
            "search_pro_sogou",
            "search_pro_quark",
        }
        assert catalog.json()["reader"]["billingStatus"] == "UNKNOWN"

        created = client.post(
            "/api/v1/event-pack-factory/builds",
            headers=HEADERS,
            json={"title": "Public liquidity event"},
        )
        assert created.status_code == 201
        build = created.json()

        hidden = client.get(
            f"/api/v1/event-pack-factory/builds/{build['id']}",
            headers={"X-Session-ID": OTHER_OWNER},
        )
        assert hidden.status_code == 404

        added = client.post(
            f"/api/v1/event-pack-factory/builds/{build['id']}/paste",
            headers=HEADERS,
            json={
                "expectedRevision": 0,
                "source": {
                    "title": "Exchange notice",
                    "publisher": "Example Exchange",
                    "url": "https://example.com/notices/liquidity-event",
                    "publishedAt": "2026-07-20T12:00:00Z",
                    "knownAt": "2026-07-20T12:05:00Z",
                    "rawText": rawText,
                    "verifiedEvidenceQuotes": [evidenceQuote],
                },
            },
        )
        assert added.status_code == 201
        assert "PRIVATE_RAW_TAIL_83b7f2" not in added.text
        source = added.json()["sources"][0]

        approved = client.post(
            (f"/api/v1/event-pack-factory/builds/{build['id']}/sources/{source['id']}/review"),
            headers=HEADERS,
            json={"expectedRevision": 1, "status": "APPROVED"},
        )
        assert approved.status_code == 200
        assert approved.json()["build"]["status"] == "REVIEW_READY"

        materialized = client.post(
            f"/api/v1/event-pack-factory/builds/{build['id']}/materialize",
            headers=HEADERS,
            json={
                "clientRequestId": "factory-materialize-request-0001",
                "expectedRevision": 2,
                "title": "Public liquidity event",
                "titleZh": "公开流动性事件",
                "summary": "A source-backed event for a liquidity stress-test workflow.",
                "summaryZh": "一个用于流动性压力测试的来源可追溯事件。",
                "asOf": "2026-07-20T13:00:00Z",
                "instrument": "TEST",
                "maximumClaims": 8,
                "requestedImpactChannels": ["belief", "liquidity"],
                "acknowledgedContentReview": True,
            },
        )
        assert materialized.status_code == 201, materialized.text
        eventPack = materialized.json()
        assert eventPack["id"].startswith("custom-public-liquidity-event-")
        assert eventPack["status"] == "DRAFT"
        assert eventPack["editableExtraction"] is True
        assert eventPack["claims"]
        assert all(claim["reviewStatus"] == "AI_PROPOSED" for claim in eventPack["claims"])
        assert all("rawText" not in item for item in eventPack["sources"])
        assert "PRIVATE_RAW_TAIL_83b7f2" not in str(eventPack["sources"])

    with TestClient(createApp(dataDir=tmp_path)) as restarted:
        listed = restarted.get(
            "/api/v1/event-pack-factory/builds",
            headers=HEADERS,
        )
        assert [item["id"] for item in listed.json()["items"]] == [build["id"]]
        deleted = restarted.request(
            "DELETE",
            f"/api/v1/event-pack-factory/builds/{build['id']}",
            headers=HEADERS,
            json={"expectedRevision": 2},
        )
        assert deleted.status_code == 204
        missing = restarted.get(
            f"/api/v1/event-pack-factory/builds/{build['id']}",
            headers=HEADERS,
        )
        assert missing.status_code == 404


def test_factory_search_requires_matching_temporary_zhipu_credential(
    tmp_path: Path,
) -> None:
    with TestClient(createApp(dataDir=tmp_path)) as client:
        build = client.post(
            "/api/v1/event-pack-factory/builds",
            headers=HEADERS,
            json={"title": "Search boundary"},
        ).json()
        response = client.post(
            f"/api/v1/event-pack-factory/builds/{build['id']}/search",
            headers=HEADERS,
            json={
                "clientRequestId": "factory-search-request-0001",
                "expectedRevision": 0,
                "request": {
                    "query": "public exchange event",
                    "engine": "search_std",
                    "searchIntent": True,
                    "count": 10,
                    "recency": "noLimit",
                    "contentSize": "medium",
                },
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ZHIPU_TEMPORARY_CREDENTIAL_REQUIRED"


def test_factory_raw_text_is_owner_only_no_store_and_revisioned_on_edit(
    tmp_path: Path,
) -> None:
    originalRawText = (
        "The issuer published a dated notice that remains available for human review. "
        "ORIGINAL_PRIVATE_MARKER_431d"
    )
    revisedRawText = (
        "The issuer published a corrected dated notice that remains available for review. "
        "REVISED_PRIVATE_MARKER_987a"
    )
    with TestClient(createApp(dataDir=tmp_path)) as client:
        build = client.post(
            "/api/v1/event-pack-factory/builds",
            headers=HEADERS,
            json={"title": "Raw text revision boundary"},
        ).json()
        added = client.post(
            f"/api/v1/event-pack-factory/builds/{build['id']}/paste",
            headers=HEADERS,
            json={
                "expectedRevision": 0,
                "source": {
                    "title": "Correctable issuer notice",
                    "publisher": "Example Issuer",
                    "knownAt": "2026-07-20T12:05:00Z",
                    "rawText": originalRawText,
                    "reviewSummary": "A human-checkable issuer notice.",
                    "verifiedEvidenceQuotes": [
                        "The issuer published a dated notice that remains "
                        "available for human review."
                    ],
                },
            },
        )
        source = added.json()["sources"][0]
        approved = client.post(
            f"/api/v1/event-pack-factory/builds/{build['id']}/sources/{source['id']}/review",
            headers=HEADERS,
            json={"expectedRevision": 1, "status": "APPROVED"},
        )
        assert approved.status_code == 200

        rawPath = f"/api/v1/event-pack-factory/builds/{build['id']}/sources/{source['id']}/raw-text"
        hidden = client.get(rawPath, headers={"X-Session-ID": OTHER_OWNER})
        assert hidden.status_code == 404

        fetched = client.get(rawPath, headers=HEADERS)
        assert fetched.status_code == 200
        assert "no-store" in fetched.headers["cache-control"]
        assert fetched.headers["pragma"] == "no-cache"
        assert fetched.json()["rawText"] == originalRawText
        assert fetched.json()["revision"] == 2

        revised = client.put(
            rawPath,
            headers=HEADERS,
            json={"expectedRevision": 2, "rawText": revisedRawText},
        )
        assert revised.status_code == 200, revised.text
        assert "no-store" in revised.headers["cache-control"]
        assert revised.headers["pragma"] == "no-cache"
        assert revised.json()["build"]["revision"] == 3
        revisedSource = revised.json()["sources"][0]
        assert revisedSource["reviewStatus"] == "PENDING"
        assert revisedSource["verifiedEvidenceQuotes"] == []
        assert revisedSource["reviewSummary"] == "[RAW_TEXT_REVISED_REVIEW_REQUIRED]"
        assert originalRawText not in revised.text
        assert revisedRawText not in revised.text

        refetched = client.get(rawPath, headers=HEADERS)
        assert refetched.json()["rawText"] == revisedRawText
        assert refetched.json()["revision"] == 3
